"""Standalone study plots with exact data in the accompanying JSON reports."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from model import REPORT


def main():
    summary = json.loads((REPORT / 'model-summary.json').read_text())
    rows = summary['models']
    fig, ax = plt.subplots(figsize=(8.5, 4.5), layout='constrained')
    bars = ax.bar(['M0: observed IR', 'M1: autonomous sequence', 'M2: word-boundary policy'],
                  [r['comparable_window_cycles'] for r in rows], color=['#334155', '#276749', '#9b4d13'],
                  edgecolor='black', linewidth=.7)
    for bar, row in zip(bars, rows):
        ax.annotate('{:,}'.format(row['comparable_window_cycles']),
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 5), textcoords='offset points', ha='center')
    ax.set_ylim(0, 146000)
    ax.set_ylabel('Clock cycles: layer start to physical final write')
    ax.set_title('Local accelerator window only — 3-cycle memory responder')
    ax.spines[['top', 'right']].set_visible(False)
    ax.text(.01, -.19, 'Host cold-loading and real E203 scheduling are not calibrated. No new hardware PPA measured.',
            transform=ax.transAxes, fontsize=9)
    fig.savefig(REPORT / 'local-model-comparison.png', dpi=180, bbox_inches='tight')
    plt.close(fig)

    blocks = json.loads((REPORT / 'lifetimes.json').read_text())
    selected = [b for b in blocks if b['first_write'] < 1800][:34]
    fig, ax = plt.subplots(figsize=(10, 8), layout='constrained')
    for i, block in enumerate(selected):
        input_block = block['key'].startswith('I:')
        ax.barh(i, block['release'] - block['first_write'], left=block['first_write'], height=.72,
                color='#bfdbfe' if input_block else '#d1d5db', hatch='//' if input_block else '',
                edgecolor='#1f2937', linewidth=.5)
    ax.set_yticks(range(len(selected)), [b['key'] for b in selected], fontsize=8)
    ax.invert_yaxis()
    ax.axvline(1645, color='black', linestyle='--', linewidth=1)
    ax.set_xlim(0, max(b['release'] for b in selected) + 50)
    ax.set_xlabel('M2 local model clock cycle')
    ax.set_ylabel('16-int16 block: I=input; O=output row / chunk / parity')
    ax.set_title('First-pair lifetimes: first-fit mapping fails at cycle 1645')
    ax.text(.01, -.08, '32 peak live blocks fit total capacity; capacity alone does not resolve per-bank conflicts.',
            transform=ax.transAxes, fontsize=9)
    ax.spines[['top', 'right']].set_visible(False)
    fig.savefig(REPORT / 'lifetimes-first-pairs.png', dpi=180, bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    main()
