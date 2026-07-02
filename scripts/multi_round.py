import sys, json
sys.path.insert(0, '/home/clawdette/trading-agents')
import run_virtual_tests as vt

vt.snapshot_state()
vt.reset_folio()
vt.clear_decisions()

history = []
for i in range(3):
    r = vt.run_round(i+1)
    history.append(r)
    print(f"ROUND {r['round']} acc={r['accuracy']}% cash=${r['cash_total']} errors={len(r['errors'])}")

final = vt.get_agent_cash()
print('FINAL_CASH', json.dumps(final))
total = sum(final.values())
print('TOTAL_CASH', round(total, 2))
print('PROFIT_LOSS', round(total - 300.0, 2))
print('REACHED_TARGET', r['accuracy'] >= 99.0 and total >= 300.0 and len(r['errors']) == 0)
