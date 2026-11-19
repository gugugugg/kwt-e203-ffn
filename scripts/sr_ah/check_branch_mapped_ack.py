"""Check the mapped AH response-ready cone using its own archive and wrapper."""
from review_branch_local import NAME, ROOT, SOURCE, area

path=ROOT/'scripts/sr_area/check_mapped_ack.py'
source=path.read_text().replace('activity-mapping/native-review-first','activity-mapping/native-review-branch')
context=dict(__file__=str(path),__name__='ah_mapped_ack')
exec(compile(source,str(path),'exec'),context)
context.update(ROOT=SOURCE,REPORT=area.REPORT)
context['check'](NAME)
