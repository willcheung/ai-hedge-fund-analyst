#!/usr/bin/env python3
"""Build first FLNC deep-dive modeling artifact + chart."""
from automation_paths import configured_text
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.comments import Comment
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName

OUT_MODELS = Path(configured_text('${ANALYST_WIKI_ROOT}/models'))
OUT_CHARTS = Path(configured_text('${ANALYST_WIKI_ROOT}/charts'))
OUT_MODELS.mkdir(parents=True, exist_ok=True)
OUT_CHARTS.mkdir(parents=True, exist_ok=True)
MODEL = OUT_MODELS / 'FLNC_first_deep_dive_model_2026-05-07.xlsx'
CHART = OUT_CHARTS / 'FLNC_order_backlog_chart_2026-05-07.png'

BLUE = Font(color='0000FF')
BLACK = Font(color='000000')
GREEN = Font(color='006100')
BOLD = Font(bold=True)
HEADER_FILL = PatternFill('solid', fgColor='1F4E79')
SUB_FILL = PatternFill('solid', fgColor='D9E1F2')
OUTPUT_FILL = PatternFill('solid', fgColor='BDD7EE')
GREY_FILL = PatternFill('solid', fgColor='F2F2F2')
WHITE_HEADER = Font(color='FFFFFF', bold=True)
thin = Side(style='thin', color='A6A6A6')
medium = Side(style='medium', color='1F4E79')

source_release = 'Source: Fluence Q2 FY2026 earnings release via GlobeNewswire/Markets Insider, 2026-05-06, https://markets.businessinsider.com/news/stocks/fluence-energy-inc-reports-second-quarter-2026-results-reaffirms-fiscal-year-2026-guidance-1036115296?op=1'
source_stock = 'Source: StockAnalysis FLNC overview/financials/forecast, accessed 2026-05-07, https://stockanalysis.com/stocks/flnc/'

wb = Workbook()
ws = wb.active
ws.title = 'FLNC Model'

# Layout
ws['A1'] = 'FLNC First Deep-Dive Model - Earnings Catalyst + Scenario Math'
ws['A1'].font = WHITE_HEADER
ws['A1'].fill = HEADER_FILL
ws.merge_cells('A1:H1')
ws['A2'] = 'As of 2026-05-07 | USD millions except per-share amounts | Built for CalConviction chart/tweet workflow'
ws.merge_cells('A2:H2')

# Input block
ws['A4'] = 'Key Inputs'
ws['A4'].font = WHITE_HEADER; ws['A4'].fill = HEADER_FILL
for c in range(1,5): ws.cell(4,c).fill = HEADER_FILL
inputs = [
    ('Current Price', 19.06, source_stock),
    ('Shares Outstanding (M)', 184.280287, source_release),
    ('Market Cap', '=B5*B6', 'Formula: current price x shares outstanding'),
    ('Net Cash / (Debt)', 21.18, source_stock),
    ('Enterprise Value', '=B7-B8', 'Formula: market cap minus net cash'),
    ('Q2 Revenue', 464.9, source_release),
    ('FY26 Revenue Guide Midpoint', 3400.0, source_release),
    ('FY26 Adj. EBITDA Guide Midpoint', 50.0, source_release),
    ('YTD Order Intake', 2000.0, source_release),
    ('Backlog', 5600.0, source_release),
    ('Total Liquidity', 900.0, source_release),
    ('Cash', 412.9, source_release),
    ('TTM Revenue', 2585.0, source_stock),
    ('TTM Gross Margin', 0.1167, source_stock),
    ('Analyst Avg PT', 15.71, source_stock),
    ('Hyperscaler Supply Agreements', 2, source_release),
]
for i,(label,val,comment) in enumerate(inputs, start=5):
    ws.cell(i,1).value = label
    ws.cell(i,2).value = val
    ws.cell(i,2).comment = Comment(comment, 'V')
    ws.cell(i,2).font = BLACK if isinstance(val,str) and val.startswith('=') else BLUE
    if label in {'Market Cap','Enterprise Value'}:
        ws.cell(i,2).font = BLACK
    ws.cell(i,1).fill = GREY_FILL

# Named ranges
for name, row in [('Current_Price',5),('Shares_Out',6),('Market_Cap',7),('Net_Cash',8),('EV',9),('FY26_Revenue',11),('FY26_EBITDA',12),('Backlog',14)]:
    wb.defined_names[name] = DefinedName(name, attr_text=f"'FLNC Model'!$B${row}")

# Catalyst bridge
start = 24
ws.cell(start,1).value = 'Catalyst Bridge - What Changed This Quarter'
ws.cell(start,1).font = WHITE_HEADER
for c in range(1,6): ws.cell(start,c).fill = HEADER_FILL
headers = ['Metric','Value','Why it matters','Source','Tweet use?']
for j,h in enumerate(headers,1):
    ws.cell(start+1,j).value=h; ws.cell(start+1,j).fill=SUB_FILL; ws.cell(start+1,j).font=BOLD
bridge = [
    ('Revenue miss context', '=B10', 'Revenue was not the story; growth was modest and shipment timing mattered.', 'Q2 release', 'No'),
    ('FY26 guide midpoint', '=B11', 'Management reaffirmed the year instead of cutting after the miss.', 'Q2 release', 'Yes'),
    ('YTD order intake', '=B13', 'Orders doubled YoY; forward demand matters more than current-quarter revenue.', 'Q2 release', 'Yes'),
    ('Backlog', '=B14', 'Record backlog is the core visibility datapoint.', 'Q2 release', 'Yes'),
    ('Hyperscaler MSAs', '=B20', 'Two major hyperscaler agreements; first order expected in Q3 FY26.', 'Q2 release', 'Yes'),
    ('Analyst gap', '=B19', 'Average PT below live price; market is front-running sell-side numbers.', 'StockAnalysis', 'Yes'),
]
for i,row in enumerate(bridge,start+2):
    for j,val in enumerate(row,1):
        ws.cell(i,j).value=val
        ws.cell(i,j).font = BLACK if isinstance(val,str) and val.startswith('=') else (GREEN if j==2 else BLACK)

# 2027 scenario sensitivity
sens = 36
ws.cell(sens,1).value = '2027 Scenario Sensitivity - Implied Share Price at P/E Multiple'
ws.cell(sens,1).font = WHITE_HEADER
for c in range(1,9): ws.cell(sens,c).fill=HEADER_FILL
ws.cell(sens+1,1).value = 'Assumptions'
ws.cell(sens+2,1).value = 'Revenue ($M) axis'
ws.cell(sens+3,1).value = 'Net margin axis'
ws.cell(sens+4,1).value = 'P/E multiple'
ws.cell(sens+4,2).value = 12.0; ws.cell(sens+4,2).font=BLUE; ws.cell(sens+4,2).comment=Comment('Assumption: rough mid-cycle multiple for profitable but still execution-risk storage/infrastructure supplier. Flex this.', 'V')
rev_axis = [4000,4500,5000,5500,6000]
margin_axis = [0.02,0.03,0.04,0.05,0.06]
for j, rev in enumerate(rev_axis,2):
    cell = ws.cell(sens+6,j); cell.value = rev; cell.font=BLUE; cell.fill=SUB_FILL; cell.comment=Comment('Assumption: 2027 revenue scenario axis, informed by FY26 guide midpoint and backlog/order conversion upside.', 'V')
for i, m in enumerate(margin_axis,sens+7):
    cell = ws.cell(i,1); cell.value = m; cell.font=BLUE; cell.fill=SUB_FILL; cell.comment=Comment('Assumption: 2027 net income margin scenario axis. Serenity math implies ~$288M NI on $6B revenue (~4.8%).', 'V')
    for j in range(2,7):
        c = ws.cell(i,j)
        # implied price = revenue * net margin * P/E / shares outstanding
        c.value = f'=({get_column_letter(j)}${sens+6}*$A{i}*$B${sens+4})/$B$6'
        c.font=BLACK
# highlight center near Serenity math: 5% margin / 6000 rev? actually row 0.05 col 6000
ws.cell(sens+10,6).fill = OUTPUT_FILL; ws.cell(sens+10,6).font=BOLD
ws.cell(sens+10,6).comment = Comment('Near Serenity public math: $6B revenue x ~4.8-5.0% net margin = ~$288-300M net income.', 'V')

# Methodology / tweet tab
meth = wb.create_sheet('Methodology')
meth['A1']='CalConviction Deep-Dive Methodology Change'
meth['A1'].font=WHITE_HEADER; meth['A1'].fill=HEADER_FILL; meth.merge_cells('A1:E1')
method_rows = [
    ('1', 'Source research', 'Gemini / web / filings / IR release', 'Find narrative, facts, catalysts; then fact-check the story.'),
    ('2', 'Wiki context', 'Existing ticker/theme/analyst pages', 'Compound prior thesis instead of starting from zero.'),
    ('3', 'Model layer', 'Excel scenario/DCF/comps depending on business type', 'Force the narrative through numbers.'),
    ('4', 'Chart layer', 'PNG from model', 'Only use if it explains the thesis faster than text.'),
    ('5', 'Social output', '@CalConviction tweet/draft', 'Tweet the insight, not the spreadsheet.'),
]
for j,h in enumerate(['Step','Layer','Artifact','Purpose'],1):
    meth.cell(3,j).value=h; meth.cell(3,j).font=BOLD; meth.cell(3,j).fill=SUB_FILL
for i,row in enumerate(method_rows,4):
    for j,val in enumerate(row,1): meth.cell(i,j).value=val

# Checks tab
chk = wb.create_sheet('Checks')
chk['A1']='Checks'
chk['A1'].font=WHITE_HEADER; chk['A1'].fill=HEADER_FILL
checks = [
    ('Market cap positive', '=B7>0'),
    ('EV positive', '=B9>0'),
    ('Backlog greater than FY26 revenue guide midpoint', '=B14>B11'),
    ('Terminal/sensitivity formulas present', f'=ISFORMULA(\'FLNC Model\'!B{sens+7})'),
]
for i,(label,formula) in enumerate(checks,3):
    chk.cell(i,1).value=label; chk.cell(i,2).value=formula

# Formatting
for sheet in wb.worksheets:
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            if cell.value is not None:
                cell.border = Border(bottom=thin)
    for col in range(1, min(sheet.max_column, 8)+1):
        sheet.column_dimensions[get_column_letter(col)].width = 22
ws.column_dimensions['C'].width = 55
ws.column_dimensions['D'].width = 20
ws.column_dimensions['E'].width = 14

# Number formats
for row in ws.iter_rows():
    for cell in row:
        if isinstance(cell.value, (int,float)):
            cell.number_format = '#,##0.0' if abs(cell.value) < 100 else '#,##0'
for r in range(sens+7,sens+12):
    ws.cell(r,1).number_format='0.0%'
    for c in range(2,7): ws.cell(r,c).number_format='$0.00'
for r in [18]:
    ws.cell(r,2).number_format='0.0%'

# workbook calc mode
wb.calculation.fullCalcOnLoad = True
wb.calculation.forceFullCalc = True
wb.save(MODEL)

# Need computed values for chart; use Python calculations with same sourced inputs.
import matplotlib.pyplot as plt
plt.style.use('default')
labels = ['Q2 revenue', 'FY26 guide\nmidpoint', 'YTD order\nintake', 'Backlog']
values_b = [0.4649, 3.4, 2.0, 5.6]
colors = ['#6B7280', '#60A5FA', '#2563EB', '#111827']
fig, ax = plt.subplots(figsize=(12,6.75), dpi=200)
bars = ax.bar(labels, values_b, color=colors, width=0.62)
ax.set_title('$FLNC: The revenue miss is not the catalyst. Order conversion is.', fontsize=18, weight='bold', pad=18)
ax.set_ylabel('USD billions', fontsize=11)
ax.set_ylim(0, 6.5)
ax.grid(axis='y', alpha=0.22)
ax.spines[['top','right']].set_visible(False)
for bar, val in zip(bars, values_b):
    label = f'${val:.1f}B' if val >= 1 else f'${val*1000:.0f}M'
    ax.text(bar.get_x()+bar.get_width()/2, val+0.12, label, ha='center', va='bottom', fontsize=13, weight='bold')
ax.annotate('Two hyperscaler master supply agreements\nFirst order expected in Q3 FY26', xy=(3,5.6), xytext=(2.03,6.15),
            arrowprops=dict(arrowstyle='->', color='#111827', lw=1.5), fontsize=12,
            bbox=dict(boxstyle='round,pad=0.35', fc='#EFF6FF', ec='#2563EB', alpha=1))
ax.text(0.01, -0.14, 'Sources: Fluence Q2 FY26 release (May 6, 2026); StockAnalysis market data accessed May 7, 2026. Chart by CalConviction.', transform=ax.transAxes, fontsize=9, color='#4B5563')
ax.text(0.01, 0.93, 'Stock already +40% today. The test is whether orders/backlog convert into FY27 earnings.', transform=ax.transAxes, fontsize=11, color='#111827')
fig.tight_layout()
fig.savefig(CHART, bbox_inches='tight', facecolor='white')
plt.close(fig)
print(str(MODEL))
print(str(CHART))
