#!/usr/bin/env python3
"""
reports/r_timelines.py
-----------------------
Per-ancestor chronological timelines, worldwide -- live, re-centerable.

One card per person: name, relationship to the target, generation, line, an
SVG strip of their dated events, and a table of every dated place they
touched. Every strip in the report shares one year scale -- derived from the
filtered data, never hardcoded -- so a birth in 1690 Staffordshire and a birth
in 1890 Michigan land at comparable positions and generations read as what
they are: comparable widths of time.

Undated events cannot be placed on a strip (there is no x for them), but they
are real research leads, so they still appear in the person's table. The
report says so once, rather than silently dropping them.

Unlike the original version, this report does not bake one target's ancestor
set into the HTML at generation time. It embeds the whole traced ancestor
pool -- everyone in `spec.pipeline.event_rows`, plus enough of the person
graph (father/mother links, from master_tree.csv) to re-walk ancestors of
*any* of them -- and renders entirely client-side. Picking a different
"Center on" person re-runs the same ancestor walk `core/ancestry.py` does
(ported to JS below, kept in lockstep with it) and re-renders instantly, no
server round-trip, no regenerate. The trade-off: you can only center on
someone already in this run's traced set (i.e. an ancestor of whoever the
CLI was last run with `--target` for) -- a different family branch entirely
still needs a regenerate.
"""
from __future__ import annotations

import json

from .base import Artifact, Report, RunSpec, P_MAX_GENS, P_YEAR_MAX, P_YEAR_MIN, html_artifact
from .theme import EVENT_ORDER, esc, legend, write_page

EXTRA_CSS = """
.strip{margin:10px 0 14px}
.person{scroll-margin-top:20px}
.gen-block h2{margin-top:40px}
.center-ctl{position:relative}
.center-ctl input{min-width:220px}
.center-results{position:absolute;top:100%;left:0;z-index:5;background:var(--surface-1);
 border:1px solid var(--line);border-radius:8px;margin-top:4px;max-height:280px;overflow:auto;
 min-width:280px;box-shadow:0 6px 18px rgba(0,0,0,.15);display:none}
.center-results.open{display:block}
.center-results button{display:block;width:100%;text-align:left;font:inherit;background:none;
 border:none;border-bottom:1px solid var(--line);padding:8px 12px;cursor:pointer;color:var(--text-primary)}
.center-results button:last-child{border-bottom:none}
.center-results button:hover{background:var(--surface-2)}
.center-results .rn{font-weight:600}
.center-results .ry{color:var(--text-muted);font-size:12px}
.center-now{color:var(--text-secondary);font-size:13px}
.center-now b{color:var(--text-primary)}
"""


def _to_int(v):
    try:
        if v in (None, ""):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _people_and_events(event_rows: list, tree, ancestors: dict = None) -> tuple[dict, list]:
    """PEOPLE (id -> name/sex/parent ids) for everyone traced, plus a trimmed
    EVENTS list. Generation/Relationship/Line are deliberately left out of
    EVENTS -- they're recomputed client-side for whichever person is
    currently centered, so baking in values for the CLI's default target
    would just be stale data the JS has to ignore.

    `ancestors` should be `spec.pipeline.ancestors` (the full walk_ancestors()
    result) when available. Without it, PEOPLE would only cover people who
    appear in event_rows -- i.e. who have at least one *dated* event -- and
    an ancestor with none (undated "connector" links happen in real trees)
    would be invisible to the client-side walk, silently truncating anyone
    further back on that line. event_rows alone is kept as a fallback for
    callers that genuinely have nothing else, not because it's sufficient.

    Parent links come from `tree.parents_of()` (`spec.pipeline.tree`) -- the
    exact same source `core/ancestry.py`'s walk_ancestors() itself uses --
    rather than master_tree.csv's FatherID/MotherID columns. Those columns
    come from a second, independent GEDCOM parser (gedcom_cleaner.py) that
    only keeps one FAMC per person; `tree.parents_of()` aggregates every
    FAMC a person has (adoptive + biological, or a duplicate record), so a
    person reachable multiple ways in the real tree stays reachable here.
    Each parent id is stored, not labeled father/mother -- like the original
    Python, the "father"/"mother" step label is derived from *that parent's
    own* sex at walk time (see relLabel/lineOf in ANCESTOR_WALK_JS), which is
    what correctly handles a person who has more than two FAMC parents."""
    ids_needed = set(ancestors) if ancestors else {r.get("PersonID") for r in event_rows if r.get("PersonID")}
    people: dict[str, dict] = {}
    for r in event_rows:
        pid = r.get("PersonID")
        if pid and pid in ids_needed and pid not in people:
            people[pid] = {"n": r.get("PersonName") or "", "s": r.get("Sex") or "", "p": []}
    if ancestors:
        for pid in ids_needed:
            if pid not in people:
                anc = ancestors[pid]
                people[pid] = {"n": getattr(anc, "name", "") or "", "s": getattr(anc, "sex", "") or "", "p": []}

    if tree is not None:
        # BFS rather than a plain loop over ids_needed: `ancestors` (when
        # unbounded, as the CLI runs it) is already closed under "parent of",
        # so this queue is normally empty after the first pass -- but staying
        # correct for a bounded/partial `ancestors` means being able to pull
        # in a newly-discovered parent's own parents too, not just one hop.
        queue = list(ids_needed)
        qi = 0
        while qi < len(queue):
            pid = queue[qi]
            qi += 1
            people[pid]["p"] = [p for p in tree.parents_of(pid) if p]
            for parent_id in people[pid]["p"]:
                if parent_id not in people and parent_id in tree.individuals:
                    ind = tree.individuals[parent_id]
                    people[parent_id] = {"n": ind.name or "", "s": ind.sex or "", "p": []}
                    queue.append(parent_id)

    events = []
    for r in event_rows:
        pid = r.get("PersonID")
        if pid not in ids_needed:
            continue
        events.append({
            "p": pid, "e": r.get("Event") or "Event", "d": r.get("Date") or "",
            "y": _to_int(r.get("Year")), "q": r.get("DateQualifier") or "",
            "pr": r.get("PlaceRaw") or "", "pl": r.get("PlaceLabel") or "",
            "cem": r.get("Cemetery") or "", "ca": r.get("CemeteryAddress") or "",
            "cp": r.get("CemeteryPlot") or "",
        })
    return people, events


# Ported 1:1 from core/ancestry.py's walk_ancestors()/Ancestor.relationship/.line --
# keep the two in lockstep if that algorithm ever changes.
ANCESTOR_WALK_JS = r"""
function relLabel(path){
  if(path.length===0)return'self';
  var base=path[path.length-1],g=path.length;
  if(g===1)return base;
  if(g===2)return'grand'+base;
  var greats=g-2;
  if(greats<=3)return Array(greats+1).join('great-')+'grand'+base;
  return greats+'x great-grand'+base;
}
function lineOf(path){return path.length===0?'self':(path[0]==='father'?'paternal':'maternal');}
function walkAncestors(rootId,maxGen){
  var out={};
  if(!PEOPLE[rootId])return out;
  out[rootId]={gen:0,rel:'self',line:'self'};
  var q=[[rootId,0,[]]],qi=0;
  while(qi<q.length){
    var cur=q[qi++],pid=cur[0],gen=cur[1],path=cur[2];
    if(maxGen&&gen>=maxGen)continue;
    var person=PEOPLE[pid];
    if(!person)continue;
    var parentIds=person.p||[];
    for(var i=0;i<parentIds.length;i++){
      var pid2=parentIds[i];
      if(!pid2||out[pid2]||!PEOPLE[pid2])continue;
      // Step label comes from the *parent's own* sex, exactly like
      // core/ancestry.py's walk_ancestors() -- not from a fixed
      // father/mother slot, so a person with more than two FAMC parents
      // (adoptive + biological, or a duplicate record) still labels
      // correctly instead of only ever finding "father" and "mother".
      var step=(PEOPLE[pid2].s||'').toUpperCase().indexOf('M')===0?'father':'mother';
      var newPath=path.concat([step]);
      out[pid2]={gen:gen+1,rel:relLabel(newPath),line:lineOf(newPath)};
      q.push([pid2,gen+1,newPath]);
    }
  }
  return out;
}
"""

RENDER_JS = r"""
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
var EVENT_SLOT={Birth:0,Baptism:0,Christening:0,Residence:2,Census:3,Marriage:5,Probate:6,
  Immigration:6,Naturalization:6,Emigration:6,Military:6,Death:4,Burial:1,Event:3};
function slotVar(t){return'var(--s'+(EVENT_SLOT.hasOwnProperty(t)?EVENT_SLOT[t]:3)+')';}
function niceStep(span){
  if(span<=0)return 1;
  var raw=span/7,steps=[1,2,5,10,20,25,50,100,200,250,500,1000,2000];
  for(var i=0;i<steps.length;i++)if(steps[i]>=raw)return steps[i];
  return 2000;
}
function timelineSvg(evs,ymin,ymax){
  var width=860,height=62,pad=16,axisY=height-22;
  function xOf(y){return ymax===ymin?width/2:pad+(y-ymin)/(ymax-ymin)*(width-2*pad);}
  var parts=['<svg class="strip" viewBox="0 0 '+width+' '+height+'" width="100%" height="'+height+
    '" role="img" aria-label="Timeline strip">'];
  parts.push('<line x1="'+pad+'" y1="'+axisY+'" x2="'+(width-pad)+'" y2="'+axisY+'" style="stroke:var(--line)" stroke-width="1"/>');
  if(ymax===ymin){
    parts.push('<text x="'+xOf(ymin).toFixed(1)+'" y="'+(height-6)+'" font-size="9" text-anchor="middle" style="fill:var(--text-muted)">'+ymin+'</text>');
  }else{
    var step=niceStep(ymax-ymin),y=Math.floor(ymin/step)*step;
    while(y<=ymax){
      if(y>=ymin){
        var x=xOf(y);
        parts.push('<line x1="'+x.toFixed(1)+'" y1="'+(axisY-3)+'" x2="'+x.toFixed(1)+'" y2="'+(axisY+3)+'" style="stroke:var(--text-muted)" stroke-width="1"/>');
        parts.push('<text x="'+x.toFixed(1)+'" y="'+(height-6)+'" font-size="9" text-anchor="middle" style="fill:var(--text-muted)">'+y+'</text>');
      }
      y+=step;
    }
  }
  evs.forEach(function(e){
    var x=xOf(e.y),color=slotVar(e.e),label=esc(e.e+', '+(e.d||e.y));
    parts.push('<circle cx="'+x.toFixed(1)+'" cy="'+axisY+'" r="4.5" style="fill:'+color+'" stroke="var(--surface-1)" stroke-width="1.5"><title>'+label+'</title></circle>');
  });
  parts.push('</svg>');
  return parts.join('');
}
function detailHtml(r){
  var bits=[];
  if(r.e==='Burial'){
    if(r.cem)bits.push('<span class="cem">'+esc(r.cem)+'</span>');
    if(r.ca)bits.push(esc(r.ca));
    if(r.cp)bits.push(esc(r.cp));
  }
  if(r.pr&&r.pr!==r.pl)bits.push('<span class="mut">'+esc(r.pr)+'</span>');
  return bits.join(' &middot; ');
}
function personBlock(pid,anc,rows,ymin,ymax,hasScale){
  var name=(PEOPLE[pid]&&PEOPLE[pid].n)||'(unknown)';
  var rel=anc.rel,line=anc.line;
  var dated=rows.filter(function(r){return r.y!=null;});
  var svg=(hasScale&&dated.length)?timelineSvg(dated,ymin,ymax):'<p class="mut">No dated events to plot for this person.</p>';
  var trs=rows.map(function(r){
    var dateTxt=esc(r.d||'')||'<span class="mut">undated</span>';
    if(r.q)dateTxt+=' <span class="mut">('+esc(r.q)+')</span>';
    var place=esc(r.pl||r.pr||'');
    return'<tr><td class="num">'+dateTxt+'</td><td><span class="dot" style="background:'+slotVar(r.e)+
      '"></span>'+esc(r.e)+'</td><td>'+place+'</td><td>'+detailHtml(r)+'</td></tr>';
  }).join('');
  var table='<table><thead><tr><th>Date</th><th>Event</th><th>Place</th><th>Detail</th></tr></thead><tbody>'+trs+'</tbody></table>';
  var relTxt=(rel==='self'||!rel)?'Target person':(rel.charAt(0).toUpperCase()+rel.slice(1));
  var lineTxt=(line==='self'||!line)?'':(' &middot; '+esc(line)+' line');
  return'<div class="card person" data-name="'+esc(name.toLowerCase())+'" data-line="'+esc(line)+'">'+
    '<h3>'+esc(name)+'</h3><p class="who">'+esc(relTxt)+lineTxt+'</p>'+svg+table+'</div>';
}
function render(targetId,maxGens,yearMin,yearMax){
  var anchors=walkAncestors(targetId,maxGens);
  var filtered=EVENTS.filter(function(r){
    var a=anchors[r.p];
    if(!a)return false;
    if(maxGens&&a.gen>maxGens)return false;
    if(r.y!=null){
      if(yearMin!=null&&r.y<yearMin)return false;
      if(yearMax!=null&&r.y>yearMax)return false;
    }
    return true;
  });

  var app=document.getElementById('app');
  var tgtName=(PEOPLE[targetId]&&PEOPLE[targetId].n)||targetId;
  document.getElementById('centerNow').innerHTML='Centered on <b>'+esc(tgtName)+'</b>';

  if(!filtered.length){
    app.innerHTML='<div class="note">No events match the current filters (generation / year range). Try widening them.</div>';
    return;
  }

  var byPerson={};
  filtered.forEach(function(r){(byPerson[r.p]=byPerson[r.p]||[]).push(r);});

  var years=filtered.map(function(r){return r.y;}).filter(function(y){return y!=null;});
  var hasScale=years.length>0;
  var ymin=hasScale?Math.min.apply(null,years):0, ymax=hasScale?Math.max.apply(null,years):0;
  var undatedCount=filtered.length-years.length;

  var byGen={};
  Object.keys(byPerson).forEach(function(pid){
    var gen=anchors[pid].gen||0;
    (byGen[gen]=byGen[gen]||[]).push(pid);
  });
  var genKeys=Object.keys(byGen).map(Number).sort(function(a,b){return a-b;});
  var genBlocks=genKeys.map(function(gen){
    var pids=byGen[gen].sort(function(a,b){
      var na=(PEOPLE[a]&&PEOPLE[a].n)||'',nb=(PEOPLE[b]&&PEOPLE[b].n)||'';
      return na.localeCompare(nb);
    });
    var cards=pids.map(function(pid){return personBlock(pid,anchors[pid],byPerson[pid],ymin,ymax,hasScale);}).join('');
    var label=gen===0?'Self':('Generation '+gen);
    return'<div class="gen-block" data-gen="'+gen+'"><h2>'+esc(label)+' <span class="mut num">('+pids.length+')</span></h2>'+cards+'</div>';
  });

  var usedTypes=EVENT_ORDER.filter(function(t){return filtered.some(function(r){return r.e===t;});});
  var yearChip=hasScale?(ymin+'–'+ymax):'no dated events';
  var metaChips='<div class="meta"><span class="chip">'+Object.keys(byPerson).length+' people</span>'+
    '<span class="chip">'+filtered.length+' events</span><span class="chip">'+esc(yearChip)+'</span></div>';
  var legendHtml='<div class="legend">'+usedTypes.map(function(t){
    return'<span><span class="dot" style="background:'+slotVar(t)+'"></span>'+esc(t)+'</span>';
  }).join('')+'</div>';
  var undatedNote=undatedCount?('<div class="note">'+undatedCount+' event(s) have no year and are listed in each '+
    'person’s table but cannot be plotted on the timeline strip.</div>'):'';

  app.innerHTML=metaChips+legendHtml+undatedNote+genBlocks.join('');
  TL_INDEX=null; // stale after a re-render -- rebuild lazily on next filter
  filterTimelines();
}
"""

CONTROL_JS = r"""
var TL_INDEX=null;
function tlIndex(){
  if(!TL_INDEX){
    TL_INDEX=Array.prototype.map.call(document.querySelectorAll('.gen-block'),function(block){
      return{block:block,cards:Array.prototype.map.call(block.querySelectorAll('.person'),function(card){
        return{el:card,name:card.getAttribute('data-name')||'',line:card.getAttribute('data-line')||''};
      })};
    });
  }
  return TL_INDEX;
}
function filterTimelines(){
  var q=(document.getElementById('q').value||'').trim().toLowerCase();
  var line=document.getElementById('lineSel').value;
  tlIndex().forEach(function(g){
    var any=false;
    g.cards.forEach(function(c){
      var show=(!q||c.name.indexOf(q)>-1)&&(!line||c.line===line);
      c.el.style.display=show?'':'none';
      if(show)any=true;
    });
    g.block.style.display=any?'':'none';
  });
}
var _tlDebounce=null;
function filterTimelinesDebounced(){clearTimeout(_tlDebounce);_tlDebounce=setTimeout(filterTimelines,120);}

var CURRENT_TARGET=null, MAX_GENS=DEFAULT_MAX_GENS, YEAR_MIN=DEFAULT_YEAR_MIN, YEAR_MAX=DEFAULT_YEAR_MAX;
function recenter(id){
  if(!PEOPLE[id])return;
  CURRENT_TARGET=id;
  location.hash='p='+encodeURIComponent(id);
  render(CURRENT_TARGET,MAX_GENS,YEAR_MIN,YEAR_MAX);
}
function centerSearch(){
  var q=(document.getElementById('centerQ').value||'').trim().toLowerCase();
  var box=document.getElementById('centerResults');
  if(!q){box.classList.remove('open');box.innerHTML='';return;}
  var hits=Object.keys(PEOPLE).filter(function(id){
    return(PEOPLE[id].n||'').toLowerCase().indexOf(q)>-1;
  }).slice(0,20);
  if(!hits.length){box.classList.remove('open');box.innerHTML='';return;}
  box.innerHTML=hits.map(function(id){
    var p=PEOPLE[id];
    return'<button type="button" data-id="'+esc(id)+'"><span class="rn">'+esc(p.n)+'</span></button>';
  }).join('');
  box.classList.add('open');
}
document.addEventListener('DOMContentLoaded',function(){
  var q=document.getElementById('centerQ');
  q.addEventListener('input',centerSearch);
  document.getElementById('centerResults').addEventListener('click',function(ev){
    var btn=ev.target.closest('button[data-id]');
    if(!btn)return;
    q.value='';
    document.getElementById('centerResults').classList.remove('open');
    recenter(btn.getAttribute('data-id'));
  });
  document.addEventListener('click',function(ev){
    if(!ev.target.closest('.center-ctl'))document.getElementById('centerResults').classList.remove('open');
  });
  var initial=DEFAULT_TARGET;
  var m=/p=([^&]+)/.exec(location.hash);
  if(m&&PEOPLE[decodeURIComponent(m[1])])initial=decodeURIComponent(m[1]);
  recenter(initial);
});
"""


def run(spec: RunSpec) -> list[Artifact]:
    rows = list(spec.pipeline.event_rows) if spec.pipeline else []
    out_path = spec.out_dir / "timelines.html"
    title = f"Ancestor Timelines — {spec.target_name}"

    if not rows:
        body = (f'<h1>Ancestor Timelines</h1>'
               f'<p class="sub">Chronological life events for {esc(spec.target_name)} and ancestors.</p>'
               f'<div class="note">No events available for this run.</div>')
        write_page(out_path, title, body, extra_css=EXTRA_CSS)
        return [html_artifact(out_path, "Ancestor Timelines", note="No events available.")]

    max_gens = _to_int(spec.p("max_generations"))
    year_min = _to_int(spec.p("year_min"))
    year_max = _to_int(spec.p("year_max"))

    tree = spec.pipeline.tree if spec.pipeline else None
    ancestors = spec.pipeline.ancestors if spec.pipeline else None
    people, events = _people_and_events(rows, tree, ancestors)

    toolbar = ('<div class="toolbar">'
              '<div class="center-ctl"><input type="search" id="centerQ" placeholder="Center on…" autocomplete="off">'
              '<div class="center-results" id="centerResults"></div></div>'
              '<span id="centerNow" class="center-now"></span>'
              '<input type="search" id="q" placeholder="Filter by name…" oninput="filterTimelinesDebounced()">'
              '<select id="lineSel" onchange="filterTimelines()">'
              '<option value="">All lines</option>'
              '<option value="paternal">Paternal</option>'
              '<option value="maternal">Maternal</option>'
              '<option value="self">Self</option>'
              '</select></div>')

    body = (f'<h1>Ancestor Timelines</h1>'
           f'<p class="sub">Chronological life events for whoever is centered below, one strip per ancestor, '
           f'all sharing a single year scale so generations are comparable. Pick a different person to '
           f'recenter instantly -- everyone already traced in this run is available.</p>'
           f'{toolbar}<div id="app"><p class="mut">Loading…</p></div>')

    extra_head = (
        f'<script>var PEOPLE={json.dumps(people, separators=(",", ":"))};'
        f'var EVENTS={json.dumps(events, separators=(",", ":"))};'
        f'var DEFAULT_TARGET={json.dumps(spec.target_id)};'
        f'var DEFAULT_MAX_GENS={json.dumps(max_gens)};'
        f'var DEFAULT_YEAR_MIN={json.dumps(year_min)};'
        f'var DEFAULT_YEAR_MAX={json.dumps(year_max)};'
        f'var EVENT_ORDER={json.dumps(EVENT_ORDER)};</script>'
        f'<script>{ANCESTOR_WALK_JS}{RENDER_JS}{CONTROL_JS}</script>'
    )

    write_page(out_path, title, body, extra_css=EXTRA_CSS, extra_head=extra_head)
    return [html_artifact(out_path, "Ancestor Timelines",
                          note=f"{len(people)} people traced, {len(events)} events, live re-centering")]


REPORT = Report(
    id="timelines",
    title="Ancestor Timelines",
    description=("A chronological strip and event table for every ancestor, generation by generation, "
                "worldwide -- one shared year scale so lifespans across continents and centuries are "
                "visually comparable. Re-center on anyone already traced, instantly, no regenerate."),
    run=run,
    params=[P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX],
    needs_events=True,
    needs_target=True,
    group="Research",
    order=20,
)
