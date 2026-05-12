#!/usr/bin/env python3
"""
شركة بوصلة التميز التجارية | Compass of Excellence Co.
امتياز منش بيكري — داشبورد يومي للفروع
COE Daily Dashboard — fetch.py v3.0
"""
import os, json, sys
from datetime import datetime, timedelta
import requests

ODOO_URL     = os.environ['ODOO_URL']
ODOO_DB      = os.environ['ODOO_DB']
ODOO_USER    = os.environ['ODOO_USER']
ODOO_API_KEY = os.environ['ODOO_API_KEY']
OUTPUT_FILE  = os.environ.get('OUTPUT_FILE', 'data.json')
KSA_OFFSET   = timedelta(hours=3)

BRANCH_SHORT = {
    'Jed - Hamadaniyyah (FR) (Hamadaniyyah)': 'Hamadaniyyah',
    'Jed - Marwah (FR) (Marwah)':             'Marwah',
    'Jed - Ajaweed (FR) (Ajaweed)':           'Ajaweed',
    'Medinah - Immam Bukhari (FR) (Defaa)':   'Defaa',
    'Jed- Al-Wazeeriyah (FR) (Wazeeriyah)':  'Wazeeriyah',
    'Jed - Al Safa (FR) (Safa)':              'Safa',
}

# All 9 delivery apps with commission rates (fee_rate, payment_fee, delivery_sar)
APP_MAP = {
    'hunger station': ('HungerStation', 0.16, 0.025, 12),
    'hungerstation':  ('HungerStation', 0.16, 0.025, 12),
    'keeta':          ('Keeta',         0.18, 0.025,  9),
    'ninja':          ('Ninja',         0.16, 0.025, 12),
    'taker':          ('Taker',         0.06, 0.025,  0),
    'jahez':          ('Jahez',         0.13, 0.025,  0),
    'marsool':        ('Mrsool',        0.12, 0.025, 11),
    'mrsool':         ('Mrsool',        0.12, 0.025, 11),
    'mr.mandoob':     ('Mr.Mandoob',    0.13, 0.025, 10),
    'mandoob':        ('Mr.Mandoob',    0.13, 0.025, 10),
    'toyou':          ('ToYou',         0.17, 0.025, 10),
    'to you':         ('ToYou',         0.17, 0.025, 10),
    'chefz':          ('TheChefz',      0.16, 0.025,  0),
    'the chefz':      ('TheChefz',      0.16, 0.025,  0),
}

# Canonical list of all 9 apps (always present even with 0 sales)
ALL_APPS = ['HungerStation','Keeta','Ninja','Taker','Jahez','Mrsool','Mr.Mandoob','ToYou','TheChefz']
WALK_IN  = 'ووك إن'

# App fee rates for reference
APP_FEES = {
    'HungerStation': {'fee': 0.16, 'payment': 0.025, 'delivery_sar': 12},
    'Keeta':         {'fee': 0.18, 'payment': 0.025, 'delivery_sar':  9},
    'Ninja':         {'fee': 0.16, 'payment': 0.025, 'delivery_sar': 12},
    'Taker':         {'fee': 0.06, 'payment': 0.025, 'delivery_sar':  0},
    'Jahez':         {'fee': 0.13, 'payment': 0.025, 'delivery_sar':  0},
    'Mrsool':        {'fee': 0.12, 'payment': 0.025, 'delivery_sar': 11},
    'Mr.Mandoob':    {'fee': 0.13, 'payment': 0.025, 'delivery_sar': 10},
    'ToYou':         {'fee': 0.17, 'payment': 0.025, 'delivery_sar': 10},
    'TheChefz':      {'fee': 0.16, 'payment': 0.025, 'delivery_sar':  0},
}

# Saudi week: weekdays = Sun/Mon/Tue/Wed, weekends = Thu/Fri/Sat
SAUDI_WEEKDAY_ORDER = [6, 0, 1, 2]  # Sun=6, Mon=0, Tue=1, Wed=2
SAUDI_WEEKEND_ORDER = [3, 4, 5]     # Thu=3, Fri=4, Sat=5
DAYS_AR = {0:'الاثنين',1:'الثلاثاء',2:'الأربعاء',3:'الخميس',4:'الجمعة',5:'السبت',6:'الأحد'}
DAYS_EN = {0:'Mon',1:'Tue',2:'Wed',3:'Thu',4:'Fri',5:'Sat',6:'Sun'}

def jsonrpc(service, method, args):
    r = requests.post(f'{ODOO_URL}/jsonrpc',
        json={'jsonrpc':'2.0','method':'call','id':1,
              'params':{'service':service,'method':method,'args':args}},
        timeout=90)
    r.raise_for_status()
    data = r.json()
    if 'error' in data:
        raise Exception(f"Odoo: {data['error']['data']['message']}")
    return data['result']

def authenticate():
    uid = jsonrpc('common','authenticate',[ODOO_DB,ODOO_USER,ODOO_API_KEY,{}])
    if not uid: raise Exception('Auth failed')
    return uid

def rpc(uid, model, method, args, **kw):
    return jsonrpc('object','execute_kw',
                   [ODOO_DB,uid,ODOO_API_KEY,model,method,args,kw])

def get_orders(uid, d_from, d_to):
    domain = [['date_order','>=',f'{d_from} 00:00:00'],
              ['date_order','<=',f'{d_to} 23:59:59'],
              ['state','in',['done','invoiced','paid']]]
    return rpc(uid,'pos.order','search_read',[domain],
               fields=['config_id','partner_id','amount_total','date_order'],
               limit=10000)

def short_branch(full_name):
    return BRANCH_SHORT.get(full_name, full_name.split('(')[-1].strip(')').strip())

def detect_channel(partner_name):
    if not partner_name: return WALK_IN
    low = partner_name.lower()
    for key, (app, *_) in APP_MAP.items():
        if key in low: return app
    if 'pos customer' in low or 'walk' in low or 'customer' == low.strip():
        return WALK_IN
    return WALK_IN

def agg(orders):
    rev = sum(o['amount_total'] for o in orders)
    cnt = len(orders)
    return {'revenue': round(rev,2), 'orders': cnt,
            'avg': round(rev/cnt,1) if cnt else 0, 'discount': 0}

def by_branch(orders):
    d = {}
    for o in orders:
        b = short_branch(o['config_id'][1]) if o.get('config_id') else 'Other'
        d.setdefault(b,[]).append(o)
    return {b: agg(lst) for b,lst in d.items()}

def by_channel(orders):
    """Always returns all 9 apps + Walk-In, even with 0 sales"""
    d = {app: [] for app in ALL_APPS}
    d[WALK_IN] = []
    for o in orders:
        ch = detect_channel(o['partner_id'][1] if o.get('partner_id') else '')
        d.setdefault(ch, []).append(o)
    result = {ch: agg(lst) for ch, lst in d.items()}
    # Sort: Walk-In first, then apps by revenue desc
    walk = result.pop(WALK_IN, {'revenue':0,'orders':0,'avg':0,'discount':0})
    sorted_apps = dict(sorted(result.items(), key=lambda x: x[1]['revenue'], reverse=True))
    return {WALK_IN: walk, **sorted_apps}

def by_branch_channel(orders):
    """For each branch: delivery_pct, direct revenue & orders"""
    d = {}
    for o in orders:
        b = short_branch(o['config_id'][1]) if o.get('config_id') else 'Other'
        ch = detect_channel(o['partner_id'][1] if o.get('partner_id') else '')
        is_delivery = ch != WALK_IN
        if b not in d:
            d[b] = {'direct_rev':0,'direct_ord':0,'delivery_rev':0,'delivery_ord':0}
        if is_delivery:
            d[b]['delivery_rev'] += o['amount_total']
            d[b]['delivery_ord'] += 1
        else:
            d[b]['direct_rev'] += o['amount_total']
            d[b]['direct_ord'] += 1
    result = {}
    for b, v in d.items():
        total = v['delivery_rev'] + v['direct_rev']
        result[b] = {
            'direct_rev':   round(v['direct_rev'],2),
            'direct_ord':   v['direct_ord'],
            'delivery_rev': round(v['delivery_rev'],2),
            'delivery_ord': v['delivery_ord'],
            'delivery_pct': round(v['delivery_rev']/total*100,1) if total else 0,
        }
    return result

def by_dow_detailed(orders):
    """DOW split into Saudi weekdays (Sun-Wed) and weekends (Thu-Sat)"""
    d = {i:[] for i in range(7)}
    for o in orders:
        try:
            dt = datetime.strptime(o['date_order'],'%Y-%m-%d %H:%M:%S') + KSA_OFFSET
            d[dt.weekday()].append(o)
        except: pass

    def make_day(i):
        s = agg(d[i])
        return {'day': DAYS_EN[i], 'day_ar': DAYS_AR[i], **s}

    weekdays = [make_day(i) for i in SAUDI_WEEKDAY_ORDER]
    weekends  = [make_day(i) for i in SAUDI_WEEKEND_ORDER]
    wd_rev = sum(x['revenue'] for x in weekdays)
    wd_ord = sum(x['orders'] for x in weekdays)
    we_rev = sum(x['revenue'] for x in weekends)
    we_ord = sum(x['orders'] for x in weekends)
    return {
        'weekdays': weekdays,
        'weekends':  weekends,
        'weekday_total': {'revenue':round(wd_rev,2),'orders':wd_ord,'avg':round(wd_rev/wd_ord,1) if wd_ord else 0},
        'weekend_total': {'revenue':round(we_rev,2),'orders':we_ord,'avg':round(we_rev/we_ord,1) if we_ord else 0},
    }

def get_top_products_daily(uid, d_from, d_to, limit=5):
    domain = [['order_id.date_order','>=',f'{d_from} 00:00:00'],
              ['order_id.date_order','<=',f'{d_to} 23:59:59'],
              ['order_id.state','in',['done','invoiced','paid']],
              ['price_unit','>',0],
              ['product_id.type','in',['product','consu']]]
    lines = rpc(uid,'pos.order.line','search_read',[domain],
                fields=['product_id','qty','price_subtotal_incl'],limit=20000)
    prod = {}
    for ln in lines:
        if not ln.get('product_id'): continue
        pid, pname = ln['product_id'][0], ln['product_id'][1]
        if pid not in prod:
            prod[pid] = {'id':pid,'name':pname,'qty':0,'revenue':0}
        prod[pid]['qty']     += ln.get('qty',0)
        prod[pid]['revenue'] += ln.get('price_subtotal_incl',0)
    # Fetch product codes
    if prod:
        try:
            pids = list(prod.keys())
            details = rpc(uid,'product.product','read',[pids],
                          fields=['id','default_code'])
            for p in details:
                if p['id'] in prod:
                    prod[p['id']]['code'] = p.get('default_code') or ''
        except: pass
    ranked = sorted(prod.values(), key=lambda x: x['revenue'], reverse=True)
    for p in ranked:
        p['qty']     = round(p['qty'],1)
        p['revenue'] = round(p['revenue'],2)
        # Extract English name (before | if bilingual)
        raw = p['name']
        if '|' in raw:
            raw = raw.split('|')[0].strip()
        p['name_en'] = raw
        if 'code' not in p: p['code'] = ''
    return ranked[:limit], ranked[-limit:][::-1] if len(ranked)>limit else []

def pct(a, b):
    return round((a-b)/b*100,1) if b else 0

def main():
    now_ksa   = datetime.utcnow() + KSA_OFFSET
    yest      = (now_ksa - timedelta(days=1)).strftime('%Y-%m-%d')
    dob       = (now_ksa - timedelta(days=2)).strftime('%Y-%m-%d')
    mtd_start = now_ksa.replace(day=1).strftime('%Y-%m-%d')
    prev_m_end= (now_ksa.replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
    prev_m_st = datetime.strptime(prev_m_end,'%Y-%m-%d').replace(day=1).strftime('%Y-%m-%d')
    prev_mtd_end_day = min(now_ksa.day-1, int(prev_m_end.split('-')[2]))
    prev_mtd_end = f"{prev_m_st[:7]}-{prev_mtd_end_day:02d}" if prev_mtd_end_day>0 else prev_m_st
    w_start   = (now_ksa - timedelta(days=7)).strftime('%Y-%m-%d')
    pw_start  = (now_ksa - timedelta(days=14)).strftime('%Y-%m-%d')
    pw_end    = (now_ksa - timedelta(days=8)).strftime('%Y-%m-%d')

    print(f'🔗 Connecting to {ODOO_URL}')
    uid = authenticate()
    print(f'✅ Authenticated uid={uid}')

    print('📦 Fetching orders...')
    o_yest    = get_orders(uid, yest, yest)
    o_dob     = get_orders(uid, dob, dob)
    o_mtd     = get_orders(uid, mtd_start, yest)
    o_prevmtd = get_orders(uid, prev_m_st, prev_mtd_end)
    o_week    = get_orders(uid, w_start, yest)
    o_pweek   = get_orders(uid, pw_start, pw_end)

    print('🏆 Fetching products...')
    top_d, bot_d = get_top_products_daily(uid, yest, yest)
    top_w, bot_w = get_top_products_daily(uid, w_start, yest)

    yest_agg  = agg(o_yest)
    dob_agg   = agg(o_dob)
    mtd_agg   = agg(o_mtd)
    pmtd_agg  = agg(o_prevmtd)
    week_agg  = agg(o_week)
    pweek_agg = agg(o_pweek)

    # Branch WoW
    br_week  = by_branch(o_week)
    br_pweek = by_branch(o_pweek)
    branch_wow = {}
    for b, s in br_week.items():
        prev = br_pweek.get(b,{}).get('revenue',0)
        branch_wow[b] = {'this_week':s['revenue'],'prev_week':prev,
                         'growth_pct':pct(s['revenue'],prev),
                         'orders_this':s['orders'],'avg_this':s['avg']}
    branch_wow = dict(sorted(branch_wow.items(), key=lambda x: x[1]['this_week'], reverse=True))

    data = {
        'meta': {
            'last_updated': now_ksa.strftime('%Y-%m-%d %H:%M'),
            'yesterday': yest, 'dob': dob,
            'mtd_start': mtd_start, 'week_start': w_start,
            'app_fees': APP_FEES,
        },
        'summary': {
            'yesterday': {**yest_agg,
                'dob_revenue': dob_agg['revenue'],
                'vs_dob_pct': pct(yest_agg['revenue'], dob_agg['revenue'])},
            'mtd': {**mtd_agg,
                'vs_prev_pct': pct(mtd_agg['revenue'], pmtd_agg['revenue']),
                'prev_mtd_revenue': pmtd_agg['revenue']},
            'week': {**week_agg,
                'prev_week_revenue': pweek_agg['revenue'],
                'vs_prev_pct': pct(week_agg['revenue'], pweek_agg['revenue'])},
        },
        'branches': {
            'yesterday': dict(sorted(by_branch(o_yest).items(), key=lambda x: x[1]['revenue'], reverse=True)),
            'mtd':       dict(sorted(by_branch(o_mtd).items(),  key=lambda x: x[1]['revenue'], reverse=True)),
            'week':      dict(sorted(by_branch(o_week).items(), key=lambda x: x[1]['revenue'], reverse=True)),
        },
        'channels': {
            'yesterday': by_channel(o_yest),
            'mtd':       by_channel(o_mtd),
        },
        'branch_channels': {
            'yesterday': by_branch_channel(o_yest),
            'week':      by_branch_channel(o_week),
        },
        'branch_wow': branch_wow,
        'dow_analysis': {
            'this_week': by_dow_detailed(o_week),
            'prev_week': by_dow_detailed(o_pweek),
        },
        'products_daily':  {'top': top_d, 'bot': bot_d},
        'products_weekly': {'top': top_w, 'bot': bot_w},
    }

    with open(OUTPUT_FILE,'w',encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n📋 Summary:")
    print(f"   Yesterday:  SAR {yest_agg['revenue']:>10,.0f}  ({yest_agg['orders']} orders, DoD {pct(yest_agg['revenue'],dob_agg['revenue']):+.1f}%)")
    print(f"   MTD:        SAR {mtd_agg['revenue']:>10,.0f}  (MoM {pct(mtd_agg['revenue'],pmtd_agg['revenue']):+.1f}%)")
    print(f"   Week:       SAR {week_agg['revenue']:>10,.0f}  (WoW {pct(week_agg['revenue'],pweek_agg['revenue']):+.1f}%)")
    print(f"\n✅ Saved → {OUTPUT_FILE}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
