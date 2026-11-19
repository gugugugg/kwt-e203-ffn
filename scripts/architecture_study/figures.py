"""Publication-style static plots of model evidence; unknown PPA is not plotted."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from common import REPORT

s=json.loads((REPORT/'results.json').read_text(encoding='utf-8'))
fig,axes=plt.subplots(1,3,figsize=(13,4.8))
fig.subplots_adjust(bottom=.25,top=.82,wspace=.36)
values=[s['baseline']['throughput'],s['A']['throughput_prediction'],s['B']['conditional_throughput'],s['C']['weighted_12case_throughput_prediction']]
bars=axes[0].bar(['IR','A:4x4','B*','C:terms'],values,color=['#334155','#945219','#287a60','#65518a'],edgecolor='#17212e')
for i,bar in enumerate(bars):
    if i:bar.set_hatch(['','//','..','xx'][i])
    axes[0].text(bar.get_x()+bar.get_width()/2,values[i]+25,'%.1f'%values[i],ha='center',fontsize=9)
axes[0].axhline(1000,color='#b91c1c',linestyle='--',linewidth=1)
axes[0].set_ylim(0,1200);axes[0].set_ylabel('Tasks / second');axes[0].set_title('Timing prediction / condition')
axes[1].bar(['IR','A:4x4'],[5,11],color=['#334155','#945219'],edgecolor='#17212e',hatch='//')
axes[1].set_ylabel('Private 128x16 I/O macros');axes[1].set_title('A: explicitly allocated storage');axes[1].set_ylim(0,13)
for i,v in enumerate([5,11]):axes[1].text(i,v+.2,str(v),ha='center')
labels=['IR reads','A reads'];pos=np.arange(2)
axes[2].bar(pos-.18,[819200,409600],width=.36,color='#334155',hatch='//',label='Weight')
axes[2].bar(pos+.18,[202752,405504],width=.36,color='#945219',hatch='xx',label='Input')
axes[2].set_xticks(pos,labels);axes[2].set_ylabel('16-bit macro reads / task');axes[2].set_title('Access tradeoff, not milliwatts');axes[2].legend(fontsize=9)
for ax in axes:ax.spines[['top','right']].set_visible(False)
fig.suptitle('Fixed architecture study: opportunities and costs',fontsize=15)
fig.text(.5,.07,'IR: accepted reference. A/C: local models. B*: conditional on same-cycle SS150MHz closure, not yet established.',ha='center',fontsize=9)
fig.text(.5,.025,'New whole-SoC area and average power remain unmeasured. All three routes preserve exact numerical semantics.',ha='center',fontsize=9)
fig.savefig(REPORT/'architecture-summary.png',dpi=170,bbox_inches='tight');plt.close(fig)

b=json.loads((REPORT/'C-perfect-balance-bound.json').read_text(encoding='utf-8'))
fig,ax=plt.subplots(figsize=(9,4.5))
fig.subplots_adjust(bottom=.2,top=.86)
work=[np.mean([x['cold_cycles_lower_bound'] for x in b['layers']]),s['C']['mean_cycles']]
bars=ax.bar(['C: perfect same-capacity balance bound','C: modeled grouped execution'],work,color=['#287a60','#65518a'],hatch='//',edgecolor='#17212e')
ax.axhline(150000,color='#b91c1c',linestyle='--',label='150,000-cycle average budget for 1,000 tasks/s')
for bar,v in zip(bars,work):ax.text(bar.get_x()+bar.get_width()/2,v+18000,f'{v:,.1f}',ha='center')
ax.set_ylim(0,1250000);ax.set_ylabel('Mean clock cycles across twelve tasks');ax.set_title('C: balancing alone does not remove term work');ax.legend(fontsize=8,loc='upper left')
ax.spines[['top','right']].set_visible(False)
fig.text(.5,.035,'Bound assumes 16 single-term services per clock and skips zero activations; it is not a bound for other bit-parallel hardware.',ha='center',fontsize=8)
fig.savefig(REPORT/'C-balance-bound.png',dpi=170,bbox_inches='tight');plt.close(fig)
