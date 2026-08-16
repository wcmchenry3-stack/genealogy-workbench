#!/usr/bin/env python3
"""
reports/r_locations.py
------------------------
The same events organised by place instead of by person, worldwide -- live,
re-centerable (see r_timelines.py's docstring for the "why" and the
"you can only center on someone already traced" caveat; it's identical here).

One card per distinct PlaceKey (country + region + subregion + locality --
see `core/places.PlaceRef.key`): who was there, when, what for, and whether
there is a cemetery to visit. Cards are ranked so the best research stops
come first -- a burial ground beats a residence, and a place that touches
many people beats one that touches few.

Every card gets `id="loc-..."` via a JS port of `theme.place_anchor` so the
map report can deep-link straight into the readable detail here instead of
cramming it into a map popup. The anchor scheme has to match exactly, since
place_anchors.json (written once per generation, not per re-center) is the
contract the map report reads.

Nothing here assumes the United States: places are grouped by whatever
`Country` the pipeline resolved, and region/subregion are simply blank for
the many places (most of the world) that do not have a US-style county.

Cards nest in a four-level hierarchy -- country, state/province, county,
then the card itself (city/town) -- with a header at each level that has
anything to show; levels with nothing to add (most of the world has no
county) are skipped rather than rendered empty. A matching set of native
multi-select filters lets a reader narrow to any combination of values at
each level; picking a country narrows which states/provinces are offered,
picking a state/province narrows the counties, and so on down to city.
"""
from __future__ import annotations

import csv as csvmod
import json
from pathlib import Path

from .base import Artifact, Param, Report, RunSpec, P_MAX_GENS, P_YEAR_MAX, P_YEAR_MIN, csv_artifact, html_artifact
from .r_timelines import ANCESTOR_WALK_JS, _people_and_events as _tl_people_and_events
from .theme import esc, place_anchor, write_page

P_COUNTRY = Param("country", "Country", "choice", "All",
                  "Limit the roster to one country. Leave as All to include everywhere.",
                  choices=None)

EXTRA_CSS = """
.place-country h2{margin-top:40px}
.plc-region{margin:0}
.plc-region>h3{margin:22px 0 10px 2px;padding-left:12px;border-left:3px solid var(--s0);font-size:16px}
.plc-subregion{margin:0}
.plc-subregion>h4{margin:14px 0 8px 18px;font-size:12px;text-transform:uppercase;
 letter-spacing:.06em;color:var(--text-muted)}
.plc-subregion>.card{margin-left:18px}
.roster th:nth-child(4),.roster td:nth-child(4){white-space:nowrap}
.fgrp{display:flex;flex-direction:column;gap:3px}
.fgrp label{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)}
.fgrp select{min-width:160px;max-width:220px}
select[multiple]{padding:2px;vertical-align:top}
select[multiple] option{padding:3px 6px;border-radius:4px}
.toolbar button{font:inherit;background:var(--surface-2);color:var(--text-primary);
 border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer;align-self:flex-end}
.toolbar button:hover{background:var(--surface-3)}
.toolbar .chip{align-self:flex-end;margin-bottom:1px}
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
    """Same PEOPLE shape as r_timelines.py (reused directly), but with the
    place-hierarchy fields Locations needs instead of the ones Timelines
    needs -- each report embeds only what it renders."""
    people, _unused = _tl_people_and_events(event_rows, tree, ancestors)
    ids_needed = set(people)
    events = []
    for r in event_rows:
        pid = r.get("PersonID")
        if pid not in ids_needed:
            continue
        events.append({
            "p": pid, "e": r.get("Event") or "Event", "d": r.get("Date") or "",
            "y": _to_int(r.get("Year")),
            "pk": r.get("PlaceKey") or "", "pl": r.get("PlaceLabel") or "", "pr": r.get("PlaceRaw") or "",
            "co": r.get("Country") or "Unknown", "cc": r.get("CountryCode") or "",
            "rg": r.get("Region") or "", "sr": r.get("Subregion") or "", "lc": r.get("Locality") or "",
            "cem": r.get("Cemetery") or "", "ca": r.get("CemeteryAddress") or "", "cp": r.get("CemeteryPlot") or "",
        })
    return people, events


RENDER_JS = r"""
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
var EVENT_SLOT={Birth:0,Baptism:0,Christening:0,Residence:2,Census:3,Marriage:5,Probate:6,
  Immigration:6,Naturalization:6,Emigration:6,Military:6,Death:4,Burial:1,Event:3};
function slotVar(t){return'var(--s'+(EVENT_SLOT.hasOwnProperty(t)?EVENT_SLOT[t]:3)+')';}
// 1:1 port of theme.place_anchor()
function placeAnchor(key){return'loc-'+String(key||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');}

function placeCard(c){
  var cemHtml='';
  if(c.cemeteries.length){
    var chunks=c.cemeteries.map(function(cm){
      var bits=['<span class="cem">'+esc(cm.name)+'</span>'];
      if(cm.addr)bits.push(esc(cm.addr));
      if(cm.plot)bits.push(esc(cm.plot));
      return bits.join(' &middot; ');
    });
    cemHtml='<p class="who">'+(chunks.length===1?'Cemetery':'Cemeteries')+': '+chunks.join('; ')+'</p>';
  }
  var rowsSorted=c.rows.slice().sort(function(a,b){
    var ay=a.y==null?99999:a.y, by=b.y==null?99999:b.y;
    if(ay!==by)return ay-by;
    return((PEOPLE[a.p]&&PEOPLE[a.p].n)||'').localeCompare((PEOPLE[b.p]&&PEOPLE[b.p].n)||'');
  });
  var trs=rowsSorted.map(function(r){
    var dateTxt=esc(r.d||'')||'<span class="mut">undated</span>';
    var rel=r._rel||'';
    var relTxt=(rel==='self'||!rel)?'Target person':(rel.charAt(0).toUpperCase()+rel.slice(1));
    var name=(PEOPLE[r.p]&&PEOPLE[r.p].n)||'';
    return'<tr><td>'+esc(name)+'</td><td>'+esc(relTxt)+'</td><td><span class="dot" style="background:'+
      slotVar(r.e)+'"></span>'+esc(r.e)+'</td><td class="num">'+dateTxt+'</td></tr>';
  }).join('');
  var table='<table><thead><tr><th>Person</th><th>Relationship</th><th>Event</th><th>Date</th></tr></thead><tbody>'+trs+'</tbody></table>';
  return'<div class="card" id="'+esc(c.anchor)+'" data-name="'+esc(c.label.toLowerCase())+'" '+
    'data-country="'+esc(c.country)+'" data-region="'+esc(c.region)+'" data-subregion="'+esc(c.subregion)+
    '" data-locality="'+esc(c.locality)+'">'+
    '<h3>'+esc(c.label)+'</h3><p class="who">'+c.people+' people &middot; '+c.events+' events &middot; '+esc(c.span)+'</p>'+
    cemHtml+table+'</div>';
}

function render(targetId,maxGens,yearMin,yearMax,countryFilter){
  var anchors=walkAncestors(targetId,maxGens);
  var filtered=EVENTS.filter(function(r){
    var a=anchors[r.p];
    if(!a)return false;
    if(r.y!=null){
      if(yearMin!=null&&r.y<yearMin)return false;
      if(yearMax!=null&&r.y>yearMax)return false;
    }
    if(countryFilter&&countryFilter!=='All'){
      var cq=countryFilter.toLowerCase();
      if((r.co||'').toLowerCase()!==cq&&(r.cc||'').toLowerCase()!==cq)return false;
    }
    r._rel=a.rel; r._line=a.line;
    return true;
  });

  var app=document.getElementById('app');
  var tgtName=(PEOPLE[targetId]&&PEOPLE[targetId].n)||targetId;
  document.getElementById('centerNow').innerHTML='Centered on <b>'+esc(tgtName)+'</b>';

  if(!filtered.length){
    app.innerHTML='<div class="note">No events match the current filters (generation / year range / country). Try widening them.</div>';
    return;
  }

  var places={};
  filtered.forEach(function(r){
    var key=r.pk||('??||||'+r.pr);
    var p=places[key]||(places[key]={rows:[],label:r.pl||r.pr||'Unknown place',country:r.co||'Unknown',
      countrycode:r.cc||'',region:r.rg||'',subregion:r.sr||'',locality:r.lc||''});
    p.rows.push(r);
  });

  var cards=Object.keys(places).map(function(key){
    var p=places[key],prows=p.rows;
    var peopleIds={}; prows.forEach(function(r){peopleIds[r.p]=1;});
    var years=prows.map(function(r){return r.y;}).filter(function(y){return y!=null;});
    var span=years.length?(Math.min.apply(null,years)+'–'+Math.max.apply(null,years)):'undated';
    var cemSeen={},cems=[];
    prows.forEach(function(r){
      if(r.cem){
        var k=r.cem+'|'+r.ca+'|'+r.cp;
        if(!cemSeen[k]){cemSeen[k]=1;cems.push({name:r.cem,addr:r.ca,plot:r.cp});}
      }
    });
    var hasBurial=prows.some(function(r){return r.e==='Burial';});
    return{key:key,label:p.label,country:p.country,countrycode:p.countrycode,region:p.region,
      subregion:p.subregion,locality:p.locality,people:Object.keys(peopleIds).length,events:prows.length,
      span:span,cemeteries:cems,hasBurial:hasBurial,rows:prows};
  });

  cards.sort(function(a,b){
    if(a.hasBurial!==b.hasBurial)return a.hasBurial?-1:1;
    if(a.people!==b.people)return b.people-a.people;
    if(a.events!==b.events)return b.events-a.events;
    return(a.label||'').localeCompare(b.label||'');
  });

  var seenAnchors={};
  cards.forEach(function(c){
    var base=placeAnchor(c.key);
    var n=seenAnchors[base]||0;
    seenAnchors[base]=n+1;
    c.anchor=n===0?base:(base+'-'+(n+1));
  });

  var tree={};
  cards.forEach(function(c){
    (tree[c.country]=tree[c.country]||{});
    (tree[c.country][c.region]=tree[c.country][c.region]||{});
    (tree[c.country][c.region][c.subregion]=tree[c.country][c.region][c.subregion]||[]).push(c);
  });

  var sections=Object.keys(tree).map(function(country){
    var regions=tree[country];
    var countryCards=[]; Object.keys(regions).forEach(function(rg){Object.keys(regions[rg]).forEach(function(sr){countryCards=countryCards.concat(regions[rg][sr]);});});
    var regionChunks=Object.keys(regions).map(function(region){
      var subregions=regions[region];
      var regionCards=[]; Object.keys(subregions).forEach(function(sr){regionCards=regionCards.concat(subregions[sr]);});
      var subregionChunks=Object.keys(subregions).map(function(subregion){
        var subcards=subregions[subregion];
        var cardsHtml=subcards.map(placeCard).join('');
        if(subregion){
          var selfDescribing=subregion.trim().toLowerCase().endsWith('region');
          var label=(selfDescribing||subcards[0].countrycode!=='US')?subregion:(subregion+' County');
          return'<div class="plc-subregion"><h4>'+esc(label)+' <span class="mut num">('+subcards.length+')</span></h4>'+cardsHtml+'</div>';
        }
        return'<div class="plc-subregion">'+cardsHtml+'</div>';
      });
      var regionHtml=subregionChunks.join('');
      if(region)return'<div class="plc-region"><h3>'+esc(region)+' <span class="mut num">('+regionCards.length+')</span></h3>'+regionHtml+'</div>';
      return'<div class="plc-region">'+regionHtml+'</div>';
    });
    return'<div class="place-country"><h2>'+esc(country)+' <span class="mut num">('+countryCards.length+' place'+
      (countryCards.length!==1?'s':'')+')</span></h2>'+regionChunks.join('')+'</div>';
  });

  var totalPeople={}; filtered.forEach(function(r){totalPeople[r.p]=1;});
  var burialPlaces=cards.filter(function(c){return c.hasBurial;}).length;
  var metaChips='<div class="meta"><span class="chip">'+cards.length+' places</span>'+
    '<span class="chip">'+Object.keys(tree).length+' countries</span>'+
    '<span class="chip">'+Object.keys(totalPeople).length+' people</span>'+
    '<span class="chip">'+filtered.length+' events</span>'+
    '<span class="chip">'+burialPlaces+' with burials</span></div>';

  app.innerHTML=metaChips+sections.join('');
  META=null; // stale after a re-render -- rebuilt lazily by filterPlaces()
  initPlaceFilters();
  filterPlaces();
}
"""

CONTROL_JS = r"""
var LEVELS=['country','region','subregion','locality'];
var sel={};
var META=null;

function distinct(pool,key){
  var seen={},out=[];
  pool.forEach(function(m){var v=m[key];if(!(v in seen)){seen[v]=true;out.push(v);}});
  out.sort(function(a,b){if(a==='')return 1;if(b==='')return-1;return a.localeCompare(b);});
  return out;
}
function selectedSet(node){
  var s=new Set();
  Array.prototype.forEach.call(node.selectedOptions||[],function(o){s.add(o.value);});
  return s;
}
function fillOptions(node,values){
  var keep=selectedSet(node);
  node.innerHTML='';
  values.forEach(function(v){
    var o=document.createElement('option');
    o.value=v; o.textContent=v===''?'(Unspecified)':v;
    if(keep.has(v))o.selected=true;
    node.appendChild(o);
  });
}
function rebuildCascade(){
  var selC=selectedSet(sel.country);
  var poolR=META.filter(function(m){return!selC.size||selC.has(m.country);});
  fillOptions(sel.region,distinct(poolR,'region'));
  var selR=selectedSet(sel.region);
  var poolS=poolR.filter(function(m){return!selR.size||selR.has(m.region);});
  fillOptions(sel.subregion,distinct(poolS,'subregion'));
  var selS=selectedSet(sel.subregion);
  var poolL=poolS.filter(function(m){return!selS.size||selS.has(m.subregion);});
  fillOptions(sel.locality,distinct(poolL,'locality'));
}
function initPlaceFilters(){
  if(!META){
    META=Array.prototype.map.call(document.querySelectorAll('.card'),function(card){
      return{anchor:card.id,country:card.getAttribute('data-country')||'',region:card.getAttribute('data-region')||'',
        subregion:card.getAttribute('data-subregion')||'',locality:card.getAttribute('data-locality')||'',
        name:card.getAttribute('data-name')||''};
    });
    fillOptions(sel.country,distinct(META,'country'));
  }
}
function filterPlaces(){
  rebuildCascade();
  var q=(document.getElementById('q').value||'').trim().toLowerCase();
  var selC=selectedSet(sel.country),selR=selectedSet(sel.region),selS=selectedSet(sel.subregion),selL=selectedSet(sel.locality);
  var shown=0;
  META.forEach(function(m){
    var show=true;
    if(q&&m.name.indexOf(q)===-1)show=false;
    if(show&&selC.size&&!selC.has(m.country))show=false;
    if(show&&selR.size&&!selR.has(m.region))show=false;
    if(show&&selS.size&&!selS.has(m.subregion))show=false;
    if(show&&selL.size&&!selL.has(m.locality))show=false;
    var el=document.getElementById(m.anchor);
    if(el)el.style.display=show?'':'none';
    if(show)shown++;
  });
  document.querySelectorAll('.place-country,.plc-region,.plc-subregion').forEach(function(g){
    var any=Array.prototype.some.call(g.querySelectorAll('.card'),function(c){return c.style.display!=='none';});
    g.style.display=any?'':'none';
  });
  var countEl=document.getElementById('fCount');
  if(countEl)countEl.textContent=shown+' of '+META.length+' places';
}
var _plDebounce=null;
function filterPlacesDebounced(){clearTimeout(_plDebounce);_plDebounce=setTimeout(filterPlaces,120);}
function clearPlaceFilters(){
  document.getElementById('q').value='';
  LEVELS.forEach(function(lv){Array.prototype.forEach.call(sel[lv].options,function(o){o.selected=false;});});
  filterPlaces();
}

var CURRENT_TARGET=null, MAX_GENS=DEFAULT_MAX_GENS, YEAR_MIN=DEFAULT_YEAR_MIN, YEAR_MAX=DEFAULT_YEAR_MAX, COUNTRY=DEFAULT_COUNTRY;
function recenter(id){
  if(!PEOPLE[id])return;
  CURRENT_TARGET=id;
  location.hash='p='+encodeURIComponent(id);
  render(CURRENT_TARGET,MAX_GENS,YEAR_MIN,YEAR_MAX,COUNTRY);
}
function centerSearch(){
  var q=(document.getElementById('centerQ').value||'').trim().toLowerCase();
  var box=document.getElementById('centerResults');
  if(!q){box.classList.remove('open');box.innerHTML='';return;}
  var hits=Object.keys(PEOPLE).filter(function(id){return(PEOPLE[id].n||'').toLowerCase().indexOf(q)>-1;}).slice(0,20);
  if(!hits.length){box.classList.remove('open');box.innerHTML='';return;}
  box.innerHTML=hits.map(function(id){
    return'<button type="button" data-id="'+esc(id)+'"><span class="rn">'+esc(PEOPLE[id].n)+'</span></button>';
  }).join('');
  box.classList.add('open');
}
document.addEventListener('DOMContentLoaded',function(){
  LEVELS.forEach(function(lv){sel[lv]=document.getElementById('f'+lv.charAt(0).toUpperCase()+lv.slice(1));});
  var q=document.getElementById('centerQ');
  q.addEventListener('input',centerSearch);
  document.getElementById('centerResults').addEventListener('click',function(ev){
    var btn=ev.target.closest('button[data-id]');
    if(!btn)return;
    q.value=''; document.getElementById('centerResults').classList.remove('open');
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


def _to_int(v):  # noqa: F811 (kept local + explicit; matches r_timelines.py's pattern)
    try:
        if v in (None, ""):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


# CSV export stays a snapshot of the run's default target -- there's no "live"
# roster to export once you can re-center in the browser, and this preserves
# the original artifact for anyone piping it into a spreadsheet.
CSV_COLUMNS = ["PlaceKey", "PlaceLabel", "Country", "CountryCode", "PersonName",
              "Relationship", "Line", "Generation", "Event", "Date", "Year",
              "Cemetery", "CemeteryAddress", "CemeteryPlot"]


def _filter_rows_for_csv(rows, max_gens, year_min, year_max, country):
    country_q = (country or "").strip().lower()
    want_all = country_q in ("", "all")
    out = []
    for r in rows:
        gen = _to_int(r.get("Generation"))
        if max_gens is not None and gen is not None and gen > max_gens:
            continue
        yr = _to_int(r.get("Year"))
        if yr is not None:
            if year_min is not None and yr < year_min:
                continue
            if year_max is not None and yr > year_max:
                continue
        if not want_all:
            c = (r.get("Country") or "").strip().lower()
            cc = (r.get("CountryCode") or "").strip().lower()
            if country_q not in (c, cc):
                continue
        out.append(r)
    return out


def _write_csv(path: Path, rows: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csvmod.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({
                "PlaceKey": r.get("PlaceKey") or "", "PlaceLabel": r.get("PlaceLabel") or "",
                "Country": r.get("Country") or "", "CountryCode": r.get("CountryCode") or "",
                "PersonName": r.get("PersonName") or "", "Relationship": r.get("Relationship") or "",
                "Line": r.get("Line") or "", "Generation": r.get("Generation") if r.get("Generation") is not None else "",
                "Event": r.get("Event") or "", "Date": r.get("Date") or "", "Year": r.get("Year") or "",
                "Cemetery": r.get("Cemetery") or "", "CemeteryAddress": r.get("CemeteryAddress") or "",
                "CemeteryPlot": r.get("CemeteryPlot") or "",
            })
    return path


def _write_place_anchors(spec: RunSpec, rows: list) -> None:
    """PlaceKey -> anchor id for the run's *default* target, published for
    r_map_classic.py to deep-link into. Live re-centering in the browser can
    show a different set of places (and, on a rare PlaceKey-collision, a
    different dedup suffix) than this snapshot -- the map's own live view
    computes its own anchors identically for that case; this file only needs
    to be right for the default-target view both reports render at load."""
    if not rows:
        (spec.out_dir / "place_anchors.json").write_text("{}", encoding="utf-8")
        return
    places: dict[str, dict] = {}
    for r in rows:
        key = r.get("PlaceKey") or f"??||||{r.get('PlaceRaw', '')}"
        p = places.setdefault(key, {"rows": [], "label": r.get("PlaceLabel") or r.get("PlaceRaw") or ""})
        p["rows"].append(r)
    ranked = []
    for key, p in places.items():
        prows = p["rows"]
        people_ids = {r.get("PersonID") or r.get("PersonName") for r in prows}
        has_burial = any((r.get("Event") or "") == "Burial" for r in prows)
        ranked.append((key, has_burial, len(people_ids), len(prows), p["label"] or ""))
    ranked.sort(key=lambda t: (not t[1], -t[2], -t[3], t[4]))

    seen_anchors: dict[str, int] = {}
    result = {}
    for key, *_rest in ranked:
        base = place_anchor(key)
        n = seen_anchors.get(base, 0)
        seen_anchors[base] = n + 1
        result[key] = base if n == 0 else f"{base}-{n + 1}"
    (spec.out_dir / "place_anchors.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


def run(spec: RunSpec) -> list[Artifact]:
    rows = list(spec.pipeline.event_rows) if spec.pipeline else []
    html_path = spec.out_dir / "locations.html"
    csv_path = spec.out_dir / "locations_roster.csv"
    title = f"Locations — {spec.target_name}"

    if not rows:
        body = (f'<h1>Locations</h1>'
               f'<p class="sub">Every dated place for {esc(spec.target_name)} and ancestors, worldwide.</p>'
               f'<div class="note">No events available for this run.</div>')
        write_page(html_path, title, body, extra_css=EXTRA_CSS)
        _write_csv(csv_path, [])
        return [html_artifact(html_path, "Locations", note="No events available."),
               csv_artifact(csv_path, "Place roster (CSV)", note="Empty -- no events available.")]

    max_gens = _to_int(spec.p("max_generations"))
    year_min = _to_int(spec.p("year_min"))
    year_max = _to_int(spec.p("year_max"))
    country_param = spec.p("country") or "All"

    tree = spec.pipeline.tree if spec.pipeline else None
    ancestors = spec.pipeline.ancestors if spec.pipeline else None
    people, events = _people_and_events(rows, tree, ancestors)

    toolbar = ('<div class="toolbar">'
              '<div class="center-ctl"><input type="search" id="centerQ" placeholder="Center on…" autocomplete="off">'
              '<div class="center-results" id="centerResults"></div></div>'
              '<span id="centerNow" class="center-now"></span>'
              '<input type="search" id="q" placeholder="Filter by place…" oninput="filterPlacesDebounced()">'
              '<div class="fgrp"><label for="fCountry">Country</label>'
              '<select id="fCountry" multiple size="6" onchange="filterPlaces()"></select></div>'
              '<div class="fgrp"><label for="fRegion">State / province</label>'
              '<select id="fRegion" multiple size="6" onchange="filterPlaces()"></select></div>'
              '<div class="fgrp"><label for="fSubregion">County</label>'
              '<select id="fSubregion" multiple size="6" onchange="filterPlaces()"></select></div>'
              '<div class="fgrp"><label for="fLocality">City / town</label>'
              '<select id="fLocality" multiple size="6" onchange="filterPlaces()"></select></div>'
              '<button type="button" onclick="clearPlaceFilters()">Clear filters</button>'
              '<span class="chip"><span id="fCount"></span></span>'
              '</div>')

    body = (f'<h1>Locations</h1>'
           f'<p class="sub">Every dated place for whoever is centered below, grouped by country, '
           f'state/province and county, and ranked to put the best research stops -- burial grounds, then '
           f'places that touch the most people -- first. Hold Ctrl/Cmd (or Shift for a range) to select more '
           f'than one value in a filter.</p>'
           f'{toolbar}<div id="app"><p class="mut">Loading…</p></div>')

    extra_head = (
        f'<script>var PEOPLE={json.dumps(people, separators=(",", ":"))};'
        f'var EVENTS={json.dumps(events, separators=(",", ":"))};'
        f'var DEFAULT_TARGET={json.dumps(spec.target_id)};'
        f'var DEFAULT_MAX_GENS={json.dumps(max_gens)};'
        f'var DEFAULT_YEAR_MIN={json.dumps(year_min)};'
        f'var DEFAULT_YEAR_MAX={json.dumps(year_max)};'
        f'var DEFAULT_COUNTRY={json.dumps(country_param)};</script>'
        f'<script>{ANCESTOR_WALK_JS}{RENDER_JS}{CONTROL_JS}</script>'
    )

    write_page(html_path, title, body, extra_css=EXTRA_CSS, extra_head=extra_head)

    csv_rows = _filter_rows_for_csv(rows, max_gens, year_min, year_max, country_param)
    _write_csv(csv_path, csv_rows)
    _write_place_anchors(spec, csv_rows)

    return [html_artifact(html_path, "Locations",
                          note=f"{len(people)} people traced, {len(events)} events, live re-centering"),
           csv_artifact(csv_path, "Place roster (CSV)",
                        note=f"{len(csv_rows)} event rows for {spec.target_name} (the default target)")]


REPORT = Report(
    id="locations",
    title="Locations",
    description=("Every dated event organised by place instead of by person -- one card per distinct place, "
                "worldwide, with cemetery detail and a roster of who was there and when. Ranked so the best "
                "research stops come first. Re-center on anyone already traced, instantly, no regenerate."),
    run=run,
    params=[P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX, P_COUNTRY],
    needs_events=True,
    needs_target=True,
    group="Research",
    order=21,
)
