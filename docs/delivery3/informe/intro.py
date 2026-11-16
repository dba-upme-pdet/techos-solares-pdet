import csv,statistics as st,sys
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
R=sys.argv[1]; OUT=sys.argv[2]
def load(p): return {r['mpio_code']:r for r in csv.DictReader(open(p,encoding='utf-8')) if r['prepared_buildings'] and int(r['prepared_buildings'])>0}
ms=load(R+'/outputs/buildings_ms_prepared_by_municipality.csv'); g=load(R+'/outputs/buildings_google_prepared_by_municipality.csv')
def n(x): return f"{int(round(float(x))):,}".replace(',',' ')
print(open(OUT+'/head.md',encoding='utf-8').read())
for name,d in (("Microsoft",ms),("Google",g)):
    c=[int(r['prepared_buildings']) for r in d.values()]; med=[float(r['area_m2_median']) for r in d.values()]
    print(f"- **{name}:** {n(sum(c))} edificaciones en {len(d)} municipios PDET. Por municipio: mediana {n(st.median(c))}, mínimo {n(min(c))}, máximo {n(max(c))} edificaciones. Mediana del área de huella por municipio: {st.median(med):.1f} m².".replace('.',',',1) if False else f"- **{name}:** {n(sum(c))} edificaciones en {len(d)} municipios PDET. Por municipio: mediana {n(st.median(c))}, mínimo {n(min(c))}, máximo {n(max(c))} edificaciones. Mediana del área de huella por municipio: {st.median(med):.1f} m².")
miss=sorted(ms[k]['name'].title() for k in set(ms)-set(g))
print(f"- Las dos fuentes tienen huellas en {len(set(ms)&set(g))} municipios comunes. Google no tiene huellas en {len(miss)} municipios: {', '.join(miss)}.")
print(f"- Google detecta {100*(sum(int(r['prepared_buildings']) for r in g.values())/sum(int(r['prepared_buildings']) for r in ms.values())-1):.0f} % más edificaciones que Microsoft, pero más pequeñas: el área total es casi igual (222,1 frente a 221,0 km²). La Entrega 4 compara las dos fuentes por municipio.\n")
top=sorted(ms.items(),key=lambda kv:-int(kv[1]['prepared_buildings']))[:10]
fig,ax=plt.subplots(figsize=(8,4.2)); y=range(len(top))[::-1]
ax.barh([i+0.2 for i in y],[int(r['prepared_buildings']) for _,r in top],0.4,label='Microsoft',color='#1F5FAF')
ax.barh([i-0.2 for i in y],[int(g.get(k,{}).get('prepared_buildings',0)) for k,_ in top],0.4,label='Google',color='#E08A1E')
ax.set_yticks(list(y)); ax.set_yticklabels([r['name'].title() for _,r in top]); ax.set_xlabel('Edificaciones cargadas'); ax.legend(); ax.spines[['top','right']].set_visible(False)
plt.tight_layout(); plt.savefig(OUT+'/top10.png',dpi=200)
print("![Figura 1. Diez municipios PDET con más edificaciones en Microsoft, comparados con Google. Fuente: `outputs/buildings_*_prepared_by_municipality.csv`.](top10.png){width=95%}\n")
print("**Tabla 3. Diez municipios PDET con más edificaciones (orden por Microsoft)**\n")
print("| Código | Municipio | Edif. MS | Área MS (m²) | Edif. Google | Área Google (m²) |\n| --- | --- | ---: | ---: | ---: | ---: |")
for k,r in top:
    gg=g.get(k,{}); print(f"| {k} | {r['name'].title()} | {n(r['prepared_buildings'])} | {n(r['area_m2_sum'])} | {n(gg.get('prepared_buildings',0))} | {n(gg.get('area_m2_sum',0))} |")
print(open(OUT+'/tail.md',encoding='utf-8').read())
