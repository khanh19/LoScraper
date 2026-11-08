"""Vietnamese intent catalogue; query text is a lead, never location evidence."""
from .model import CITIES, folded

ACTIVITIES = {
 'music': ['show nhạc', 'đêm nhạc', 'concert'],
 'sports': ['giải chạy', 'lịch bóng rổ', 'watch party bóng đá'],
 'nightlife': ['DJ set', 'club cuối tuần'],
 'market': ['pop up', 'hội chợ local brand', 'chợ phiên'],
 'culture': ['triển lãm', 'bảo tàng có gì mới'],
 'workshop': ['workshop làm gốm', 'lớp vẽ hẹn hò', 'boardgame'],
 'restaurant': ['lễ hội ẩm thực', 'quán mới mở'],
 'cafe': ['cafe có workshop', 'cà phê mới mở'],
 'bar': ['nhạc sống', 'cocktail bar'],
 'experience': ['cuối tuần đi đâu', 'hoạt động cùng bạn bè'],
}
ALIASES = {
 'hcmc': ['Sài Gòn','TPHCM','Thảo Điền','An Khánh','quận 1'],
 'hanoi': ['Hà Nội','Tây Hồ','Hoàn Kiếm','Hồng Hà'],
 'danang': ['Đà Nẵng','Hải Châu','Sơn Trà','An Hải'],
}

def queries(city, counts=None):
    counts=counts or {}
    out=[]
    for category in sorted(ACTIVITIES,key=lambda c:(counts.get(c,0),c)):
        phrase=f'{ACTIVITIES[category][0]} {CITIES[city]} cuối tuần này'
        out.append({'city':city,'category':category,'query':phrase,
                    'variants':[folded(phrase)]+[f'{ACTIVITIES[category][0]} {a}' for a in ALIASES[city]],
                    'eligible_count':counts.get(category,0)})
    return out
