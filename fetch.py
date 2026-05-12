#!/usr/bin/env python3
"""
شركة بوصلة التميز التجارية | Compass of Excellence Co.
امتياز Munch Bakery — داشبورد يومي للفروع
COE Daily Dashboard — fetch.py v1.0
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

APP_MAP = {
    'hunger station': 'HungerStation',
    'keeta':          'Keeta',
    'ninja':          'Ninja',
    'taker':          'Taker',
    'jahez':          'Jahez',
    'marsool':        'Marsool',
    'mrsool':         'Mrsool',
    'mr.mandoob':     'Mr.Mandoob',
    'toyou':          'ToYou',
}

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

def get_orders(uid, d_from, d_to, fields=None):
    domain = [['date_order','>=',f'{d_from} 00:00:00'],
              ['date_order','<=',f'{d_to} 23:59:59'],
              ['state','in',['done','invoiced','paid']]]
    fields = fields or ['config_id','partner_id','amount_total',
                                                'date_order']
    return rpc(uid,'pos.order','search_read',[domain],
               fields=fields, limit=10000)

def short_branch(full_name):
    return BRANCH_SHORT.get(full_name, full_name.split('(')[-1].strip(')').strip())

def detect_channel(partner_name):
    if not partner_name: return 'Direct'
    low = partner_name.lower()
    for key, app in APP_MAP.items():
        if key in low: return app
    if 'pos customer' in low or 'walk' in low: return 'Direct'
    return 'Direct'

def agg(orders):
    rev = sum(o['amount_total'] for o in orders)
    disc = 0
    cnt = len(orders)
    return {
        'revenue': round(rev,2),
        'orders':  cnt,
        'avg':     round(rev/cnt,1) if cnt else 0,
        'discount':round(disc,2),
    }

def by_branch(orders):
    d = {}
    for o in orders:
        b = short_branch(o['config_id'][1]) if o.get('config_id') else 'Other'
        d.setdefault(b,[]).append(o)
    return {b: agg(lst) for b,lst in d.items()}

def by_channel(orders):
    d = {}
    for o in orders:
        ch = detect_channel(o['partner_id'][1] if o.get('partner_id') else '')
        d.setdefault(ch,[]).append(o)
    result = {ch: agg(lst) for ch,lst in d.items()}
    # sort by revenue desc
    return dict(sorted(result.items(), key=lambda x: x[1]['revenue'], reverse=True))

def by_dow(orders):
    """توزيع حسب يوم الأسبوع (0=Mon)"""
    DAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    d = {i:[] for i in range(7)}
    for o in orders:
        try:
            dt = datetime.strptime(o['date_order'],'%Y-%m-%d %H:%M:%S') + KSA_OFFSET
            d[dt.weekday()].append(o)
        except: pass
    return [{'day': DAYS[i], 'day_ar': ['الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'][i],
             **agg(d[i])} for i in range(7)]

def get_top_products(uid, d_from, d_to, limit=5):
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
        pid,pname = ln['product_id'][0], ln['product_id'][1]
        if pid not in prod:
            prod[pid] = {'name':pname,'qty':0,'revenue':0,'orders':0}
        prod[pid]['qty']     += ln.get('qty',0)
        prod[pid]['revenue'] += ln.get('price_subtotal_incl',0)
        prod[pid]['orders']  += 1
    ranked = sorted(prod.values(), key=lambda x: x['revenue'], reverse=True)
    for p in ranked:
        p['qty']     = round(p['qty'],1)
        p['revenue'] = round(p['revenue'],2)
    return ranked[:limit], ranked[-limit:][::-1] if len(ranked)>limit else []

def pct(a, b):
    return round((a-b)/b*100,1) if b else 0

def main():
    now_ksa   = datetime.utcnow() + KSA_OFFSET
    today     = now_ksa.strftime('%Y-%m-%d')
    yest      = (now_ksa - timedelta(days=1)).strftime('%Y-%m-%d')
    dob       = (now_ksa - timedelta(days=2)).strftime('%Y-%m-%d')
    mtd_start = now_ksa.replace(day=1).strftime('%Y-%m-%d')
    prev_m_end= (now_ksa.replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
    prev_m_st = datetime.strptime(prev_m_end,'%Y-%m-%d').replace(day=1).strftime('%Y-%m-%d')
    # Same-day-count last month for fair MTD comparison
    prev_mtd_end_day = min(now_ksa.day-1,
                           int(prev_m_end.split('-')[2]))
    prev_mtd_end = f"{prev_m_st[:7]}-{prev_mtd_end_day:02d}" if prev_mtd_end_day>0 else prev_m_st
    w_start   = (now_ksa - timedelta(days=7)).strftime('%Y-%m-%d')
    pw_start  = (now_ksa - timedelta(days=14)).strftime('%Y-%m-%d')
    pw_end    = (now_ksa - timedelta(days=8)).strftime('%Y-%m-%d')
    dow_start = (now_ksa - timedelta(days=30)).strftime('%Y-%m-%d')

    print(f'🔗 Connecting to {ODOO_URL}')
    uid = authenticate()
    print(f'✅ Authenticated uid={uid}')

    print('📦 Fetching orders...')
    o_yest  = get_orders(uid, yest, yest)
    o_dob   = get_orders(uid, dob, dob)
    o_mtd   = get_orders(uid, mtd_start, yest)
    o_prevmtd = get_orders(uid, prev_m_st, prev_mtd_end)
    o_week  = get_orders(uid, w_start, yest)
    o_pweek = get_orders(uid, pw_start, pw_end)
    o_dow   = get_orders(uid, dow_start, yest)

    print('🏆 Fetching top products...')
    top5, bot5 = get_top_products(uid, w_start, yest)

    yest_agg  = agg(o_yest)
    dob_agg   = agg(o_dob)
    mtd_agg   = agg(o_mtd)
    pmtd_agg  = agg(o_prevmtd)
    week_agg  = agg(o_week)
    pweek_agg = agg(o_pweek)

    data = {
        'meta': {
            'last_updated': now_ksa.strftime('%Y-%m-%d %H:%M'),
            'yesterday':    yest,
            'mtd_start':    mtd_start,
            'week_start':   w_start,
        },
        'summary': {
            'yesterday': {**yest_agg,
                'vs_dob_pct': pct(yest_agg['revenue'], dob_agg['revenue'])},
            'mtd':       {**mtd_agg,
                'vs_prev_pct': pct(mtd_agg['revenue'], pmtd_agg['revenue']),
                'prev_mtd_revenue': pmtd_agg['revenue']},
            'week':      {**week_agg,
                'vs_prev_pct': pct(week_agg['revenue'], pweek_agg['revenue'])},
        },
        'branches': {
            'yesterday': dict(sorted(by_branch(o_yest).items(),
                              key=lambda x: x[1]['revenue'], reverse=True)),
            'mtd':       dict(sorted(by_branch(o_mtd).items(),
                              key=lambda x: x[1]['revenue'], reverse=True)),
            'week':      dict(sorted(by_branch(o_week).items(),
                              key=lambda x: x[1]['revenue'], reverse=True)),
        },
        'channels': {
            'yesterday': by_channel(o_yest),
            'mtd':       by_channel(o_mtd),
        },
        'dow':          by_dow(o_dow),
        'top_products': top5,
        'bot_products': bot5,
    }

    with open(OUTPUT_FILE,'w',encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n📋 Summary:")
    print(f"   Yesterday:  SAR {yest_agg['revenue']:>10,.0f}  ({yest_agg['orders']} orders)")
    print(f"   DoD change: {pct(yest_agg['revenue'],dob_agg['revenue']):+.1f}%")
    print(f"   MTD:        SAR {mtd_agg['revenue']:>10,.0f}")
    print(f"   MoM change: {pct(mtd_agg['revenue'],pmtd_agg['revenue']):+.1f}%")
    print(f"\n✅ Saved → {OUTPUT_FILE}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
