import sqlite3,csv,collections,re,json,pathlib,datetime
ROOT=pathlib.Path(__file__).resolve().parents[1]
c=sqlite3.connect(f'file:{ROOT}/voltanord.sqlite?mode=ro',uri=True);c.row_factory=sqlite3.Row
T={t:[dict(r) for r in c.execute('select * from '+t)] for t in ['customers','sites','meters','contracts','tariffs']}
R={name:list(csv.DictReader(open(ROOT/(name+'.csv'),encoding='utf-8-sig',newline=''))) for name in ['ref_departements_regions','ref_stations_meteo']}
issues=[];checks=[]
def check(source,label,rows,action='Quarantaine Silver / examen métier',severity='anomalie',code=None):
 ids=[str(x) for x in rows];checks.append((source,label,len(ids)));
 if ids:issues.append(dict(source=source,symptom=label,count=len(ids),examples=ids[:5],action=action,severity=severity,code=code or label))
def blank(v):return v is None or isinstance(v,str) and not v.strip()
def validdate(x):
 try:datetime.date.fromisoformat(str(x));return True
 except:return False
for t,rows in T.items():
 pk={'customers':'customer_id','sites':'site_id','meters':'meter_id','contracts':'contract_id','tariffs':'tariff_code'}[t]
 check(t,'Clé primaire absente/vide',[r.get(pk) for r in rows if blank(r.get(pk))]);co=collections.Counter(r[pk] for r in rows);check(t,'Clé primaire dupliquée',[r[pk] for r in rows if co[r[pk]]>1])
 for field in rows[0]:
  n=sum(blank(r[field]) for r in rows);checks.append((t,'Valeurs nulles/vides : '+field,n))
ids={t:{r[{'customers':'customer_id','sites':'site_id','meters':'meter_id','contracts':'contract_id','tariffs':'tariff_code'}[t]] for r in rs} for t,rs in T.items()}
for t,f,ref in [('sites','customer_id','customers'),('meters','site_id','sites'),('contracts','customer_id','customers'),('contracts','site_id','sites')]:check(t,f'FK {f} absente de {ref}',[r[f] for r in T[t] if r[f] not in ids[ref]])
site={r['site_id']:r for r in T['sites']};check('contracts','Client du contrat différent du client du site',[r['contract_id'] for r in T['contracts'] if r['site_id'] in site and r['customer_id']!=site[r['site_id']]['customer_id']])
check('meters','PRM différent de 14 caractères',[r['meter_id'] for r in T['meters'] if len(str(r['meter_id']))!=14]);check('meters','PRM non numérique',[r['meter_id'] for r in T['meters'] if not str(r['meter_id']).isdigit()])
for t,fields in [('customers',['created_at','updated_at']),('meters',['install_date','removal_date']),('contracts',['start_date','end_date']),('tariffs',['valid_from','valid_to'])]:
 for f in fields:
  check(t,'Date invalide : '+f,[str(i) for i,r in enumerate(T[t],1) if not blank(r[f]) and not validdate(str(r[f])[:10])])
check('customers','updated_at antérieur à created_at',[r['customer_id'] for r in T['customers'] if r['updated_at']<r['created_at']])
check('meters','Retrait antérieur à installation',[r['meter_id'] for r in T['meters'] if r['removal_date'] and r['install_date'] and r['removal_date']<r['install_date']])
check('contracts','Fin antérieure au début',[r['contract_id'] for r in T['contracts'] if r['end_date'] and r['end_date']<r['start_date']])
check('tariffs','Validité inversée',[r['tariff_code'] for r in T['tariffs'] if r['valid_to']<r['valid_from']])
for t,f,allowed in [('customers','customer_type',{'PARTICULIER','PRO'}),('contracts','tariff_option',{'BASE','HPHC','PRO'}),('tariffs','tariff_option',{'BASE','HPHC','PRO'})]:check(t,'Domaine inconnu '+f,[str(i) for i,r in enumerate(T[t],1) if r[f] not in allowed])
check('contracts','Puissance souscrite non positive',[r['contract_id'] for r in T['contracts'] if r['subscribed_kva']<=0])
check('sites','Surface négative ou nulle',[r['site_id'] for r in T['sites'] if r['surface_m2'] is not None and r['surface_m2']<=0])
check('customers','Email non vide avec format manifestement invalide',[r['customer_id'] for r in T['customers'] if not blank(r['email']) and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',r['email'].strip())])
check('customers','Email avec espaces périphériques',[r['customer_id'] for r in T['customers'] if r['email'] and r['email']!=r['email'].strip()],action='Normaliser en Silver (trim), conserver brut en Bronze')
check('customers','Email avec majuscules',[r['customer_id'] for r in T['customers'] if r['email'] and r['email']!=r['email'].lower()],action='Normaliser en Silver (lower), conserver brut en Bronze')
check('customers','IBAN absent',[r['customer_id'] for r in T['customers'] if blank(r['iban'])],action='Documenter / ne pas inventer')
check('customers','IBAN structure FR invalide',[r['customer_id'] for r in T['customers'] if not blank(r['iban']) and not re.fullmatch(r'FR\d{25}',re.sub(r'\s+','',r['iban']).upper())])
for f in ['price_base','price_hp','price_hc','price_kva_month']:check('tariffs','Prix négatif : '+f,[r['tariff_code'] for r in T['tariffs'] if r[f] is not None and r[f]<0])
for t,group,key,lo,hi in [('tariffs','tariff_option','tariff_code','valid_from','valid_to'),('contracts','site_id','contract_id','start_date','end_date'),('meters','site_id','meter_id','install_date','removal_date')]:
 rows=T[t];pairs=[]
 for g in set(r[group] for r in rows):
  arr=[r for r in rows if r[group]==g and r[lo]]
  for i,a in enumerate(arr):
   for b in arr[i+1:]:
    if a[lo]<=(b[hi] or '9999-12-31') and b[lo]<=(a[hi] or '9999-12-31'):pairs.append(f'{a[key]} + {b[key]}')
 check(t,f'Paires de périodes chevauchantes par {group}',pairs,action='Vérification métier : ne pas dédupliquer automatiquement')
for name,rows in R.items():
 checks.append((name,'Nombre de lignes',len(rows)))
 for f in rows[0]:checks.append((name,'Valeurs nulles/vides : '+f,sum(blank(r[f]) for r in rows)))
 for f in ['code_departement' if 'departements' in name else 'num_poste']:
  co=collections.Counter(r[f] for r in rows);check(name,'Identifiant dupliqué '+f,[r[f] for r in rows if co[r[f]]>1])
regions={r['code_region'] for r in R['ref_departements_regions']};check('ref_stations_meteo','Station avec région non référencée',[r['num_poste'] for r in R['ref_stations_meteo'] if r['code_region'] not in regions])
co=collections.Counter(r['code_region'] for r in R['ref_stations_meteo']);check('ref_stations_meteo','Région avec plusieurs stations',[r['num_poste'] for r in R['ref_stations_meteo'] if co[r['code_region']]>1])
check('ref_stations_meteo','Coordonnées GPS hors bornes',[r['num_poste'] for r in R['ref_stations_meteo'] if not(-90<=float(r['lat'])<=90 and -180<=float(r['lon'])<=180)])
check('sites','Région libellée non présente dans référentiel',[r['site_id'] for r in T['sites'] if not blank(r['region_label']) and r['region_label'].strip().casefold() not in {x['nom_region'].strip().casefold() for x in R['ref_departements_regions']}],action='Normaliser avec référentiel après vérification des alias')
check('sites','Code postal absent',[r['site_id'] for r in T['sites'] if blank(r['postal_code'])],action='Quarantaine enrichissement géographique')
check('sites','Code postal non conforme à cinq chiffres',[r['site_id'] for r in T['sites'] if not blank(r['postal_code']) and not re.fullmatch(r'\d{5}',str(r['postal_code']))])
# Additional diagnostics
check('customers','Client PRO sans raison sociale',[r['customer_id'] for r in T['customers'] if r['customer_type']=='PRO' and blank(r['company_name'])])
check('meters','Compteur sans date installation',[r['meter_id'] for r in T['meters'] if blank(r['install_date'])],action='Vérifier historique avant calcul des périodes')
check('contracts','Contrat actif avec date de fin avant extraction initiale',[r['contract_id'] for r in T['contracts'] if r['status']=='ACTIF' and r['end_date'] and r['end_date']<'2026-01-01'])
output={'inventory':{k:len(v) for k,v in {**T,**R}.items()},'issues':issues,'checks':checks}
(ROOT/'audit'/'resultats_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print('issues',len(issues));print('\n'.join(f"{x['source']} | {x['symptom']} | {x['count']} | {x['examples']}" for x in issues))
