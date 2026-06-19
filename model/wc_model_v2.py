# -*- coding: utf-8 -*-
"""
WORLDCUP KING OF BET - Moteur v2.0 (post-audit, 12/06/2026)
Corrections : marge=dElo/175 (cap 2.5) | T couple a |m| + reprojection floor |
de-vig power (biais favori-outsider) | blend 30% modele, amorti sur outsiders |
edge window 3-12%, anomalies >15% rejetees | Kelly portefeuille (cap 12% expo) |
DC dans le Monte-Carlo | tiebreak head-to-head | module buteurs (Poisson aminci)
"""
import json, math, random, csv, os
ROOT="/sessions/vibrant-eager-einstein/mnt/Worldcup king of bet"
from collections import defaultdict
random.seed(42)
ELO_PER_GOAL=175.0; MARGIN_CAP=2.5; T_COUPLE=0.30; W_ELO=0.80; SHRINK=0.50
BASE=2.52; RHO=-0.12; MAXG=10; NS=20000
ALPHA=0.30; EDGE_MIN=0.03; EDGE_MAX=0.12; EDGE_ANOM=0.15
KFRAC=0.25; KCAP=0.02; EXPO_MAX=0.12
T=json.load(open(ROOT+"/data/teams.json",encoding="utf-8"))
M=json.load(open(ROOT+"/data/matches.json",encoding="utf-8"))
O=json.load(open(ROOT+"/data/odds.json",encoding="utf-8"))
SC=json.load(open(ROOT+"/data/scorers.json",encoding="utf-8"))
# === v2.2 : ELO DYNAMIQUE INTRA-TOURNOI (K=60, formule eloratings.net) + SHRINKAGE xG ===
K_ELO=60; XG_W=0.6; SHRINK_K=7.0
_match_count={}
for p in sorted(M["played"], key=lambda x:x["date"]):
    h,a=p["home"],p["away"]; sh,sa=p["score"]
    d=(T[h]["elo"]+T[h].get("host_bonus",0))-(T[a]["elo"]+T[a].get("host_bonus",0))
    we=1/(1+10**(-d/400.0))
    W=1.0 if sh>sa else (0.0 if sh<sa else 0.5)
    nd=abs(sh-sa)
    G=1.0 if nd<=1 else (1.5 if nd==2 else (11+nd)/8.0)
    delta=K_ELO*G*(W-we)
    T[h]["elo"]+=delta; T[a]["elo"]-=delta
    xg=p.get("xg")  # optionnel : [xg_dom, xg_ext] si collecte FBref dispo
    for team,gf,ga,i in ((h,sh,sa,0),(a,sa,sh,1)):
        gfe=XG_W*xg[i]+(1-XG_W)*gf if xg else gf
        gae=XG_W*xg[1-i]+(1-XG_W)*ga if xg else ga
        _match_count[team]=_match_count.get(team,0)+1
        w=1.0/(_match_count[team]+SHRINK_K)
        T[team]["att"]+= w*(gfe/1.3 - T[team]["att"])
        T[team]["def"]+= w*(gae/1.3 - T[team]["def"])
am=sum(t["att"] for t in T.values())/len(T); dm=sum(t["def"] for t in T.values())/len(T)
for t in T.values():
    t["att_n"]=1+SHRINK*(t["att"]/am-1); t["def_n"]=1+SHRINK*(t["def"]/dm-1)
def eelo(n,pen=0):
    t=T[n]; return t["elo"]+t["adj"]+t.get("host_bonus",0)+pen
def lambdas(h,a,ph=0,pa=0,hot=False):
    th,ta=T[h],T[a]; dr=eelo(h,ph)-eelo(a,pa)
    m_elo=max(-MARGIN_CAP,min(MARGIN_CAP,dr/ELO_PER_GOAL))
    lh0=BASE/2*th["att_n"]*ta["def_n"]; la0=BASE/2*ta["att_n"]*th["def_n"]
    m=W_ELO*m_elo+(1-W_ELO)*(lh0-la0)
    Tt=max(1.9,min(4.2,lh0+la0+T_COUPLE*abs(m_elo)))
    lh,la=(Tt+m)/2,(Tt-m)/2
    if la<0.15: la=0.15; lh=Tt-0.15
    if lh<0.15: lh=0.15; la=Tt-0.15
    return lh,la
def pois(l,k): return math.exp(-l)*l**k/math.factorial(k)
def tau(x,y,lh,la):
    if x==0 and y==0: return 1-lh*la*RHO
    if x==0 and y==1: return 1+lh*RHO
    if x==1 and y==0: return 1+la*RHO
    if x==1 and y==1: return 1-RHO
    return 1.0
def matrix(lh,la):
    Mx=[[pois(lh,i)*pois(la,j)*tau(i,j,lh,la) for j in range(MAXG)] for i in range(MAXG)]
    s=sum(sum(r) for r in Mx); return [[v/s for v in r] for r in Mx]
def devig_power(odds3):
    inv=[1/o for o in odds3]
    lo,hi=0.5,3.0
    for _ in range(60):
        k=(lo+hi)/2; s=sum(p**k for p in inv)
        if s>1: lo=k
        else: hi=k
    k=(lo+hi)/2; ps=[p**k for p in inv]; s=sum(ps)
    return [p/s for p in ps]
def pool_probs(mkt):
    srcs=mkt.get("sources")
    if not srcs:
        return devig_power([mkt["h"],mkt["d"],mkt["a"]])
    pooled=[1.0,1.0,1.0]; tw=0.0
    for s in srcs:
        ps=devig_power([s["h"],s["d"],s["a"]]); w=s.get("w",1.0); tw+=w
        for i in range(3): pooled[i]*=ps[i]**w
    pooled=[p**(1.0/max(tw,1e-9)) for p in pooled]
    tot=sum(pooled)
    return [p/tot for p in pooled]
# === v2.3 : MOTEUR DE MATCHUPS (facteurs : postes, style, mental, chaleur, banc) ===
import os as _os
FACT = json.load(open(ROOT+"/data/factors.json",encoding="utf-8")) if _os.path.exists(ROOT+"/data/factors.json") else {}
def matchup(h, a, hot=False):
    fh, fa = FACT.get(h), FACT.get(a)
    if not fh or not fa: return 0.0, []
    adv = []; score = 0.0
    # duels croises par poste (seuil : ecart >= 2)
    duels = [
        (fh["ailes"]-fa["lateraux"], 0.50, "Ailes %s vs lateraux %s"%(h,a)),
        (fa["ailes"]-fh["lateraux"], -0.50, "Ailes %s vs lateraux %s"%(a,h)),
        (fh["attaque"]-fa["def_centrale"], 0.60, "Attaque %s vs charniere %s"%(h,a)),
        (fa["attaque"]-fh["def_centrale"], -0.60, "Attaque %s vs charniere %s"%(a,h)),
    ]
    for d, w, lab in duels:
        if d >= 2:
            score += abs(w)*d*(1 if w>0 else -1)
            adv.append(lab+" (+%d)"%d)
    dm = fh["milieu"]-fa["milieu"]
    if abs(dm) >= 2:
        score += 0.8*dm
        adv.append("Bataille du milieu : %s (+%d)"%(h if dm>0 else a, abs(dm)))
    dmen = (fh["mental"]-fa["mental"])
    if abs(dmen) >= 2:
        score += 0.4*dmen
        adv.append("Mental/vecu : %s (+%d)"%(h if dmen>0 else a, abs(dmen)))
    dg = fh["gardien"]-fa["gardien"]
    if abs(dg) >= 3:
        score += 0.3*dg
        adv.append("Gardien : %s (+%d)"%(h if dg>0 else a, abs(dg)))
    db = fh["profondeur_banc"]-fa["profondeur_banc"]
    if abs(db) >= 3:
        score += 0.2*db
        adv.append("Profondeur de banc : %s"%(h if db>0 else a))
    if hot:
        dc_ = fh["chaleur"]-fa["chaleur"]
        if abs(dc_) >= 2:
            score += 0.6*dc_
            adv.append("Chaleur/conditions : %s (+%d)"%(h if dc_>0 else a, abs(dc_)))
    # interactions de style
    if fh["style"]=="pressing" and fa["milieu"]<=5:
        score += 0.8; adv.append("Pressing %s vs relance faible %s"%(h,a))
    if fa["style"]=="pressing" and fh["milieu"]<=5:
        score -= 0.8; adv.append("Pressing %s vs relance faible %s"%(a,h))
    if fa["style"]=="bloc_bas" and fh["attaque"]<=5 and fh["ailes"]<=6:
        adv.append("Bloc bas %s vs attaque limitee %s : nul possible"%(a,h))
    if fh["style"]=="bloc_bas" and fa["attaque"]<=5 and fa["ailes"]<=6:
        adv.append("Bloc bas %s vs attaque limitee %s : nul possible"%(h,a))
    fadj = max(-15.0, min(15.0, score*4.0))  # borne stricte : facteurs <= 15 pts Elo
    return fadj, adv
FADJ = {}
for _mt in M["remaining"]:
    FADJ[_mt["id"]] = matchup(_mt["home"], _mt["away"], _mt.get("hot", False))
def mlam(mt):
    return lambdas(mt["home"], mt["away"],
                   mt.get("penalty_home",0)+FADJ[mt["id"]][0],
                   mt.get("penalty_away",0), mt.get("hot",False))
res_rows=[]; values=[]; anomalies=[]; preds=[]
for mt in M["remaining"]:
    mid=str(mt["id"]); mkt=O.get(mid)
    lh,la=mlam(mt)
    Mx=matrix(lh,la)
    p1=sum(Mx[i][j] for i in range(MAXG) for j in range(MAXG) if i>j)
    pn=sum(Mx[i][i] for i in range(MAXG)); p2=1-p1-pn
    o25=sum(Mx[i][j] for i in range(MAXG) for j in range(MAXG) if i+j>=3)
    btts=sum(Mx[i][j] for i in range(1,MAXG) for j in range(1,MAXG))
    top=sorted(((i,j,Mx[i][j]) for i in range(MAXG) for j in range(MAXG)),key=lambda x:-x[2])[:3]
    edges_out=[]
    if mkt:
        mp=pool_probs(mkt)
        for i,(pm,co,lab) in enumerate(((p1,mkt["h"],"1"),(pn,mkt["d"],"N"),(p2,mkt["a"],"2"))):
            al=ALPHA
            if co>=4 and pm>mp[i]: al=ALPHA*max(0.0,1-4*(pm-mp[i]))
            pf=al*pm+(1-al)*mp[i]
            edge=pf*co-1; b=co-1
            kelly=max(0.0,(pf*b-(1-pf))/b) if b>0 else 0
            stake=min(KCAP,KFRAC*kelly)
            edges_out.append({"sel":lab,"cote":co,"pm":round(pm*100,1),"pmkt":round(mp[i]*100,1),
                              "pf":round(pf*100,1),"edge":round(edge*100,1),"stake":round(stake*100,2)})
            d={"date":mt["date"],"match":mt["home"]+" - "+mt["away"],"sel":lab,"cote":co,
               "p_model":pm*100,"p_mkt":mp[i]*100,"p_fin":pf*100,"edge":edge*100,"stake":stake*100,
               "est":mkt.get("est",False)}
            if edge>EDGE_ANOM: anomalies.append(d)
            elif EDGE_MIN<edge<=EDGE_MAX and pf>=0.15 and not mkt.get("est",False): values.append(d)
    preds.append({"id":mt["id"],"date":mt["date"],"grp":mt["group"],"home":mt["home"],"away":mt["away"],
        "p1":round(p1*100,1),"pn":round(pn*100,1),"p2":round(p2*100,1),
        "f1":round(1/p1,2),"fn":round(1/pn,2),"f2":round(1/p2,2),
        "o25":round(o25*100,1),"btts":round(btts*100,1),"xgh":round(lh,2),"xga":round(la,2),
        "scores":[[i,j,round(p*100,1)] for i,j,p in top],
        "mkt":({"h":mkt["h"],"d":mkt["d"],"a":mkt["a"],"o25":mkt.get("o25"),"btts":mkt.get("btts"),"est":mkt.get("est",False)} if mkt else None),
        "edges":edges_out})
    res_rows.append([mt["date"],mt["group"],mt["home"]+" - "+mt["away"],
        "%.1f"%(p1*100),"%.1f"%(pn*100),"%.1f"%(p2*100),"%.2f"%(1/p1),"%.2f"%(1/pn),"%.2f"%(1/p2),
        "%.1f"%(o25*100),"%.1f"%(btts*100),"%.2f"%lh,"%.2f"%la,
        " / ".join("%d-%d %.0f%%"%(i,j,p*100) for i,j,p in top)])
# Kelly portefeuille
tot=sum(v["stake"] for v in values)/100
if tot>EXPO_MAX:
    f=EXPO_MAX/tot
    for v in values: v["stake"]*=f
# Buteurs
lamc={mt["id"]:mlam(mt) for mt in M["remaining"]}
minfo={mt["id"]:mt for mt in M["remaining"]}
scorers=[]
for s in SC:
    mt=minfo.get(s["mid"])
    if not mt: continue
    lh,la=lamc[s["mid"]]
    lam=lh if s["team"]==mt["home"] else la
    p=1-math.exp(-lam*s["s"]*s["mins"])
    edge=p*s["cote"]-1
    scorers.append({"player":s["player"],"team":s["team"],"match":mt["home"]+" - "+mt["away"],
        "date":mt["date"],"cote":s["cote"],"p":round(p*100,1),"edge":round(edge*100,1)})
scorers.sort(key=lambda x:-x["edge"])
# Monte-Carlo (tirage dans la matrice DC, tiebreak h2h)
flat={}
for mt in M["remaining"]:
    lh,la=lamc[mt["id"]]; Mx=matrix(lh,la)
    flat[mt["id"]]=([(i,j) for i in range(MAXG) for j in range(MAXG)],
                    [Mx[i][j] for i in range(MAXG) for j in range(MAXG)])
groups=defaultdict(list)
for nm,t in T.items(): groups[t["group"]].append(nm)
c1=defaultdict(int);c2=defaultdict(int);c3=defaultdict(int);cq=defaultdict(int)
def rank_group(tl,pts,gd,gf,h2h):
    def key(t): return (pts[t],gd[t],gf[t])
    order=sorted(tl,key=lambda t:(key(t),random.random()),reverse=True)
    out=[];i=0
    while i<len(order):
        tied=[x for x in order if key(x)==key(order[i]) and x not in out]
        if len(tied)>1:
            hp=defaultdict(int)
            for (a,b),(sa,sb) in h2h.items():
                if a in tied and b in tied:
                    hp[a]+=3 if sa>sb else (1 if sa==sb else 0)
                    hp[b]+=3 if sb>sa else (1 if sa==sb else 0)
            tied.sort(key=lambda t:(hp[t],random.random()),reverse=True)
        out.extend(tied); i=len(out)
    return out
for _ in range(NS):
    pts=defaultdict(int);gd=defaultdict(int);gf=defaultdict(int);h2h={}
    def app(h,a,sh,sa):
        gd[h]+=sh-sa;gd[a]+=sa-sh;gf[h]+=sh;gf[a]+=sa;h2h[(h,a)]=(sh,sa)
        pts[h]+=3 if sh>sa else (1 if sh==sa else 0)
        pts[a]+=3 if sa>sh else (1 if sh==sa else 0)
    for p in M["played"]: app(p["home"],p["away"],p["score"][0],p["score"][1])
    for mt in M["remaining"]:
        sc_,w=flat[mt["id"]]; i,j=random.choices(sc_,weights=w)[0]
        app(mt["home"],mt["away"],i,j)
    thirds=[]
    for g,tl in groups.items():
        o=rank_group(tl,pts,gd,gf,h2h)
        c1[o[0]]+=1;c2[o[1]]+=1;cq[o[0]]+=1;cq[o[1]]+=1;thirds.append(o[2])
    thirds.sort(key=lambda t:(pts[t],gd[t],gf[t],random.random()),reverse=True)
    for t in thirds[:8]: c3[t]+=1;cq[t]+=1
qual=[]
for g in sorted(groups):
    for t in sorted(groups[g],key=lambda t:-cq[t]):
        qual.append({"grp":g,"team":t,"p1":round(c1[t]/NS*100,1),"p2":round(c2[t]/NS*100,1),
                     "p3q":round(c3[t]/NS*100,1),"pq":round(cq[t]/NS*100,1)})
# Tickets (v2.1 : favoris au blend pf, leans si pas de value stricte)
def best_pf(p):
    if not p["edges"]: return None
    e=max(p["edges"],key=lambda x:x["pf"])
    side=p["home"]+" bat "+p["away"] if e["sel"]=="1" else (p["away"]+" bat "+p["home"] if e["sel"]=="2" else "Nul "+p["home"]+"-"+p["away"])
    return {"sel":side,"cote":e["cote"],"p":e["pf"],"date":p["date"],"est":p["mkt"]["est"]}
nd=sorted(set(p["date"] for p in preds))[:5]
cand=[best_pf(p) for p in preds if p["date"] in nd and p["mkt"]]
cand=[c for c in cand if c and c["p"]>=72]
cand.sort(key=lambda c:-c["p"])
sl=cand[:3]
all_edges=[]
for p in preds:
    if not p["mkt"] or p["mkt"]["est"]: continue
    for e in p["edges"]:
        if 1.6<=e["cote"]<=3.5 and e["edge"]<=EDGE_ANOM*100:
            side=p["home"]+" bat "+p["away"] if e["sel"]=="1" else (p["away"]+" bat "+p["home"] if e["sel"]=="2" else "Nul "+p["home"]+"-"+p["away"])
            all_edges.append({"sel":side,"cote":e["cote"],"p":e["pf"],"date":p["date"],"edge":e["edge"]})
all_edges.sort(key=lambda x:-x["edge"])
bal=all_edges[:2]
fun=[s for s in scorers if s["edge"]>0][:3]
def prod(l):
    r=1.0
    for x in l: r*=x
    return r
tickets={
 "sur":{"legs":sl,"cote":round(prod([s["cote"] for s in sl]),2) if sl else 0},
 "equilibre":{"legs":bal,"cote":round(prod([v["cote"] for v in bal]),2) if bal else 0},
 "fun":{"legs":[{"sel":s["player"]+" buteur ("+s["match"]+")","cote":s["cote"],"p":s["p"],"date":s["date"],"edge":s["edge"]} for s in fun],"cote":round(prod([s["cote"] for s in fun]),2) if fun else 0}
}
# Sorties
os.makedirs(ROOT+"/output",exist_ok=True)
with open(ROOT+"/output/predictions.csv","w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f,delimiter=";")
    w.writerow(["Date","Grp","Match","P1 %","PN %","P2 %","Cote juste 1","N","2","Over2.5 %","BTTS %","xG dom","xG ext","Scores probables"])
    w.writerows(res_rows)
with open(ROOT+"/output/qualification.csv","w",newline="",encoding="utf-8-sig") as f:
    w=csv.writer(f,delimiter=";")
    w.writerow(["Groupe","Equipe","P(1er)%","P(2e)%","P(3e repeche)%","P(qualif)%"])
    for q in qual: w.writerow([q["grp"],q["team"],q["p1"],q["p2"],q["p3q"],q["pq"]])
_factors_out={str(k):{"adj":round(v[0],1),"adv":v[1]} for k,v in FADJ.items()}
app_data={"generated":"2026-06-12","version":"v2.0","played":M["played"],"predictions":preds,
          "qualification":qual,"values":values,"anomalies":anomalies,"scorers":scorers,"tickets":tickets,"factors":_factors_out,"profils":FACT}
with open(ROOT+"/app/app_data.js","w",encoding="utf-8") as f:
    f.write("const APP_DATA = "+json.dumps(app_data,ensure_ascii=False)+";")
print("=== VALUE BETS v2 (edge 3-12%, cotes reelles, apres garde-fous) ===")
for v in sorted(values,key=lambda x:-x["edge"]):
    print("%s %-30s [%s] cote %.2f | mod %.0f%% mkt %.0f%% fin %.1f%% | edge +%.1f%% | mise %.2f%%"%(
        v["date"],v["match"],v["sel"],v["cote"],v["p_model"],v["p_mkt"],v["p_fin"],v["edge"],v["stake"]))
print("--- ANOMALIES rejetees (edge>15%% = suspicion erreur) ---")
for a in anomalies: print("%s %s [%s] cote %.2f edge +%.0f%%"%(a["date"],a["match"],a["sel"],a["cote"],a["edge"]))
print("=== BUTEURS (P modele vs cote) ===")
for s in scorers[:8]: print("%-18s %-28s cote %.2f | P %.0f%% | edge %+.0f%%"%(s["player"],s["match"],s["cote"],s["p"],s["edge"]))
print("=== TICKETS ===")
print(json.dumps(tickets,ensure_ascii=False,indent=1))
print("=== QUALIF (top par groupe) ===")
for g in sorted(groups):
    print("Grp %s: "%g+", ".join("%s %.0f%%"%(q["team"],q["pq"]) for q in qual if q["grp"]==g))
print("OK -> output/*.csv + app/app_data.js")

# ================= AGENT PARIEUR VIRTUEL (paper trading) =================
BKCFG=json.load(open(ROOT+"/data/bankroll.json",encoding="utf-8"))
PB_PATH=ROOT+"/data/paper_bets.json"
if os.path.exists(PB_PATH):
    PB=json.load(open(PB_PATH,encoding="utf-8"))
else:
    PB={"bankroll_start":BKCFG["bankroll_initiale"],"bankroll":BKCFG["bankroll_initiale"],"bets":[]}
# --- 1. Reglement des paris 1N2 en attente via les resultats ---
played_idx={(p["home"],p["away"]):p["score"] for p in M["played"]}
for b in PB["bets"]:
    if b["status"]!="pending" or b["market"]!="1N2": continue
    key=tuple(b["match"].split(" - "))
    if key in played_idx:
        sh,sa=played_idx[key]
        out="1" if sh>sa else ("2" if sa>sh else "N")
        if out==b["sel"]:
            b["status"]="won"; b["pl"]=round(b["stake"]*(b["cote"]-1),2)
        else:
            b["status"]="lost"; b["pl"]=-b["stake"]
        PB["bankroll"]=round(PB["bankroll"]+b["pl"],2)
# --- 2. Nouveaux paris du jour (strategie prudente, idempotent) ---
def already(mid,sel,market):
    return any(b for b in PB["bets"] if b.get("mid")==mid and b["sel"]==sel and b["market"]==market)
expo_pending=sum(b["stake"] for b in PB["bets"] if b["status"]=="pending")
budget=max(0.0,PB["bankroll"]*BKCFG["expo_max"]-expo_pending)
new_bets=[]
for v in sorted(values,key=lambda x:-x["edge"]):
    mid_v=next((p["id"] for p in preds if p["home"]+" - "+p["away"]==v["match"]),None)
    if already(mid_v,v["sel"],"1N2"): continue
    stake=round(min(PB["bankroll"]*v["stake"]/100,budget),2)
    if stake<0.5: continue
    budget-=stake
    new_bets.append({"id":len(PB["bets"])+len(new_bets)+1,"placed":app_data["generated"],"mid":mid_v,
        "match":v["match"],"market":"1N2","sel":v["sel"],"cote":v["cote"],"stake":stake,
        "edge":round(v["edge"],1),"status":"pending","pl":0})
for s in scorers:
    if s["edge"]<5: continue
    mid_s=next((p["id"] for p in preds if p["home"]+" - "+p["away"]==s["match"]),None)
    if already(mid_s,s["player"],"buteur"): continue
    stake=round(min(PB["bankroll"]*0.015,budget),2)
    if stake<0.5: continue
    budget-=stake
    new_bets.append({"id":len(PB["bets"])+len(new_bets)+1,"placed":app_data["generated"],"mid":mid_s,
        "match":s["match"],"market":"buteur","sel":s["player"],"cote":s["cote"],"stake":stake,
        "edge":s["edge"],"status":"pending","pl":0})
PB["bets"].extend(new_bets)
json.dump(PB,open(PB_PATH,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
# --- 3. Injection dans l'app ---
app_data["paper"]=PB
with open(ROOT+"/app/app_data.js","w",encoding="utf-8") as f:
    f.write("const APP_DATA = "+json.dumps(app_data,ensure_ascii=False)+";")
print("=== AGENT PARIEUR ===")
print("Bankroll: %.2f EUR (depart %.2f) | paris ouverts: %d | nouveaux aujourd'hui: %d"%(
    PB["bankroll"],PB["bankroll_start"],sum(1 for b in PB["bets"] if b["status"]=="pending"),len(new_bets)))
for b in new_bets: print("  + %s [%s] %s cote %.2f mise %.2f EUR (edge +%.1f%%)"%(b["match"],b["market"],b["sel"],b["cote"],b["stake"],b["edge"]))
