import streamlit as st, pandas as pd, numpy as np, json

st.set_page_config(page_title="DC102 SDVM Simulator", layout="wide")
WEEKDAYS = ['Mon','Tues','Wed','Thur','Fri']

def load_db():
    stores = pd.read_csv('data/stores.csv')
    cons   = json.load(open('data/constraints.json'))
    targets= json.load(open('data/targets.json'))
    return stores, cons, targets

def save_db(stores, cons):
    stores.to_csv('data/stores.csv', index=False)
    json.dump(cons, open('data/constraints.json','w'), indent=2)

def compute_mix(df):
    n = len(df)
    return {d: float((df['ScenarioFreq']==d).sum()/n) for d in [2,3,4,5]}

def drop_points(df):
    return {d:int(df[d].sum()) for d in WEEKDAYS}

def fleet_rte(df):
    local = {d: float(df[(df['Group']=='Local') & (df[d]==1)]['AvgRTE'].sum()) for d in WEEKDAYS}
    mth   = {d: float(df[(df['Distance'].str.contains('COUNTRY MTHATHA', case=False, na=False)) & (df[d]==1)]['AvgRTE'].sum()) for d in WEEKDAYS}
    other = {d: float(df[(~df['Group'].eq('Local')) & (~df['Distance'].str.contains('COUNTRY MTHATHA', case=False, na=False)) & (df[d]==1)]['AvgRTE'].sum()) for d in WEEKDAYS}
    return local, mth, other

def feasible(df, cons):
    dp = drop_points(df)
    if any(dp[d] > cons['DropPointsLimit'] for d in WEEKDAYS): return False
    local, mth, other = fleet_rte(df)
    if any(local[d] > cons['Local_Trucks'] * cons['Local_8ton_RTE_Capacity']   for d in WEEKDAYS): return False
    if any(mth[d]   > cons['Pantec_Trucks_Mthatha'] * cons['Pantec_RTE_Capacity'] for d in WEEKDAYS): return False
    if any(other[d] > cons['Country_12ton_Trucks'] * cons['Country_12ton_RTE_Capacity'] for d in WEEKDAYS): return False
    return True

def auto_distribute(df):
    for d in WEEKDAYS: df[d] = 0
    for i, r in df.iterrows():
        f = int(r['ScenarioFreq'])
        loads = {d:int(df[d].sum()) for d in WEEKDAYS}
        for d in sorted(WEEKDAYS, key=lambda x: loads[x])[:f]:
            df.at[i, d] = 1
    return df

def penalty(df, tgt):
    mix = compute_mix(df)
    return (mix[2]-tgt['two'])**2 + (mix[3]-tgt['three'])**2 + (mix[4]-tgt['four'])**2 + (mix[5]-tgt['five'])**2

def goal_seek(df, cons, tgt, iters=1500):
    df = df.copy()
    df = auto_distribute(df)
    best = df.copy()
    best_pen = penalty(best, tgt)
    for _ in range(iters):
        improved = False
        for i in range(len(df)):
            f0 = int(df.at[i,'ScenarioFreq'])
            for nf in [f0-1, f0+1]:
                if nf < 2 or nf > 5: 
                    continue
                df.at[i,'ScenarioFreq'] = nf
                df = auto_distribute(df)
                if feasible(df, cons):
                    pen = penalty(df, tgt)
                    if pen + 1e-9 < best_pen:
                        best, best_pen, improved = df.copy(), pen, True
                    else:
                        df.at[i,'ScenarioFreq']=f0
                        df = auto_distribute(df)
                else:
                    df.at[i,'ScenarioFreq']=f0
                    df = auto_distribute(df)
        if not improved:
            break
    return best, best_pen

stores, cons, targets = load_db()
st.title('DC102 – SDVM Scenario Simulator (Web)')

# Sidebar – constraints
with st.sidebar:
    st.header('Constraints')
    cons['DropPointsLimit'] = st.number_input('Drop-points limit', 1, 500, int(cons['DropPointsLimit']))
    cons['Local_Trucks']    = st.number_input('Local trucks (8-ton)', 0, 50, int(cons['Local_Trucks']))
    cons['Local_8ton_RTE_Capacity'] = st.number_input('8-ton RTE cap/day', 1, 200, int(cons['Local_8ton_RTE_Capacity']))
    cons['Pantec_Trucks_Mthatha']   = st.number_input('Mthatha Pantec trucks', 0, 10, int(cons['Pantec_Trucks_Mthatha']))
    cons['Pantec_RTE_Capacity']     = st.number_input('Pantec RTE cap/day', 1, 200, int(cons['Pantec_RTE_Capacity']))
    cons['Country_12ton_Trucks']    = st.number_input('12-ton trucks (Other Country)', 0, 20, int(cons['Country_12ton_Trucks']))
    cons['Country_12ton_RTE_Capacity'] = st.number_input('12-ton RTE cap/day', 1, 300, int(cons['Country_12ton_RTE_Capacity']))
    if st.button('Save constraints'): 
        save_db(stores, cons)
        st.success('Saved.')

st.subheader('Store scenarios (edit ScenarioFreq and/or days)')
editable = stores[['StoreCode','StoreName','Distance','Route','Group','AvgRTE','ScenarioFreq'] + WEEKDAYS].copy()
edit     = st.data_editor(editable, use_container_width=True)
stores['ScenarioFreq'] = edit['ScenarioFreq'].clip(2,5).astype(int)
for d in WEEKDAYS: 
    stores[d] = edit[d].astype(int)

c1,c2,c3,c4 = st.columns(4)
if c1.button('Auto-distribute days'): 
    stores = auto_distribute(stores); 
    save_db(stores, cons); 
    st.experimental_rerun()
if c2.button('Check feasibility'): 
    st.info('Feasible' if feasible(stores, cons) else 'NOT feasible – adjust plan')
if c3.button('Goal-seek to 2026'): 
    best, pen = goal_seek(stores, cons, targets['2026']); 
    stores.update(best); 
    st.success(f'Penalty={pen:.6f}'); 
    save_db(stores, cons)
if c4.button('Save scenario'): 
    save_db(stores, cons); 
    st.success('Scenario saved.')

st.subheader('Summary')
mix = compute_mix(stores); st.write('SDVM mix:', {k:f'{v*100:.1f}%' for k,v in mix.items()})
st.write('Drop-points/day:', drop_points(stores))
L, M, O = fleet_rte(stores)
st.write('Local RTE/day:', {k:round(v,1) for k,v in L.items()})
st.write('Mthatha RTE/day:', {k:round(v,1) for k,v in M.items()})
st.write('Other Country RTE/day:', {k:round(v,1) for k,v in O.items()})
st.download_button('Download current scenario CSV', stores.to_csv(index=False).encode('utf-8'), 'dc102_scenario_export.csv', 'text/csv')
