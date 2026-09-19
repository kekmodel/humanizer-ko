#!/usr/bin/env python3
"""fidelity_check.py — 윤문 전후 의미 보존·과윤문 게이트 (결정적, 표준 라이브러리만).

사용:
    python3 fidelity_check.py --before 원문.txt --after 윤문.txt [--json]

exit code
    0  자동 검사에서 이상 없음 — 의미 보존 보증은 아님
    1  경고 — 결과를 전달해도 되지만 해당 항목을 사용자에게 알린다
    2  중단 — 윤문본을 채택하지 말고 문제 구간을 되돌린 뒤 다시 검사한다
    3  입력 오류

검사 항목 (왜 이렇게 재는가)
- 변경률: difflib 문자 유사도. 단, 이 공식은 '삭제'를 절반으로 세기 때문에(30% 삭제 = 17.6%)
  길이비(len_ratio)를 함께 본다. 두 값은 검토 신호이며 의미 변경 여부를 판정하지 않는다.
- 수치·단위·날짜: 원문의 숫자 토큰은 하나도 사라지거나 새로 생기면 안 된다.
- 영문 토큰(약어·고유명사): LLM·GPU·API 같은 표준 용어를 직역하거나 지우면 실패.
- 따옴표 구간: 짧은 구간도 보존 검사. 강조·용어 표기일 수도 있으므로 불일치는 검토 경고.
- 한글 수량·부정·서법 표지: 일부 표현의 변화만 감지한다. 누락과 오탐이 있어 직접 대조가 필요하다.
- 각주 표지 [^n]·[n]: 집합이 같아야 한다.
- '하였' 증가: 격식 상향 금지(원문 '했'을 '하였'로 바꾸는 건 register 위반).
- 해요체·합쇼체 급감: 구어 종결을 평서로 떨어뜨렸다는 신호.
- 연결어미 뒤 쉼표 증가: 윤문이 새 AI 티(C-11)를 주입한 것.
- 문장 전면 수정 비율: 탐지되지 않은 문장까지 손댔는지. Pebblous 티어다운의 지적
  ("리페어 레이어가 자기 지문을 남긴다")에 대응한다.
"""
import argparse
import difflib
import json
import re
import sys
from collections import Counter

sys.path.insert(0, __import__("os").path.dirname(__file__))
try:
    from tell_scan import split_sentences, count_ending_commas, sentence_has_tell  # noqa: E402
except Exception:  # 단독 실행 대비 최소 구현
    def split_sentences(text):
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]

    def count_ending_commas(sentences):
        return []

    def sentence_has_tell(s):
        return True

NUM_RE = re.compile(r"\d[\d,\.]*\s?(%|퍼센트|배|억|만|천|조|원|달러|명|개|건|년|월|일|시|분|초|km|m|kg|g|GB|MB|TB)?")
LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-\.+#]{1,}")
QUOTE_RE = re.compile(r""""([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|(?<![A-Za-z])'([^'\n]+)'(?![A-Za-z])""")
KO_QUANTITY_RE = re.compile(
    r"(?<![가-힣])(?:(?:스물|서른|마흔|쉰|예순|일흔|여든|아흔)?\s*"
    r"(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무)|십|백|천)"
    r"\s*(?:가지|개|명|건|번|회|년|달|개월|일|시간|분|초|배)(?=$|[^가-힣]|[이가은는을를의도만다]|간|부터|까지)"
    r"|(?<![가-힣])(?:절반|반수|전부|모두)(?=$|[^가-힣]|[이가은는을를의도만])"
)
SEMANTIC_CUES = {
    "부정": re.compile(r"없[가-힣]*|않[가-힣]*|못하[가-힣]*|아니[가-힣]*|(?<![가-힣])(?:안|못)\s"),
    "당위": re.compile(r"[가-힣]+야\s*(?:한다|합니다|할|한|하|해|되)[가-힣]*|필요하다|필요합니다"),
    "추측·가능성": re.compile(r"수\s*(?:있|없)[가-힣]*|것으로\s*보[가-힣]*|가능성[가-힣]*"),
}


def quoted_spans(text):
    return [next(v for v in match.groups() if v is not None) for match in QUOTE_RE.finditer(text)]


FOOTNOTE_RE = re.compile(r"\[\^?\d+\]")
POLITE_RE = re.compile(r"(요|죠|네요|군요|습니다|입니다|십니까|습니까)[.!?]")
HAYEOT_RE = re.compile(r"하였")


def norm_num(tok: str) -> str:
    return re.sub(r"\s", "", tok)


def strip_markup(t: str) -> str:
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    return t


def multiset_diff(a, b):
    ca, cb = Counter(a), Counter(b)
    missing = list((ca - cb).elements())
    added = list((cb - ca).elements())
    return missing, added


def check(before: str, after: str) -> dict:
    b_plain, a_plain = strip_markup(before), strip_markup(after)
    ratio = difflib.SequenceMatcher(None, b_plain, a_plain, autojunk=False).ratio()
    change_rate = round((1 - ratio) * 100, 1)
    len_b = len(re.sub(r"\s", "", b_plain)) or 1
    len_a = len(re.sub(r"\s", "", a_plain))
    len_ratio = round(len_a / len_b, 3)

    nums_missing, nums_added = multiset_diff(
        [norm_num(m.group(0)) for m in NUM_RE.finditer(before)],
        [norm_num(m.group(0)) for m in NUM_RE.finditer(after)],
    )
    lat_missing, lat_added = multiset_diff(LATIN_RE.findall(before), LATIN_RE.findall(after))
    # 대소문자만 다른 경우는 무시
    lat_missing = [x for x in lat_missing if x.lower() not in {y.lower() for y in LATIN_RE.findall(after)}]

    quotes_broken, quotes_added = multiset_diff(quoted_spans(before), quoted_spans(after))
    ko_missing, ko_added = multiset_diff(
        [norm_num(m.group()) for m in KO_QUANTITY_RE.finditer(before)],
        [norm_num(m.group()) for m in KO_QUANTITY_RE.finditer(after)],
    )
    # 표지 변화는 검토 후보일 뿐이다. 동의어, 문장 병합, 표지 위치 교환은 직접 확인한다.
    semantic_changes = [name for name, rx in SEMANTIC_CUES.items()
                        if Counter(rx.findall(before)) != Counter(rx.findall(after))]

    fn_missing, fn_added = multiset_diff(FOOTNOTE_RE.findall(before), FOOTNOTE_RE.findall(after))

    hayeot_b, hayeot_a = len(HAYEOT_RE.findall(before)), len(HAYEOT_RE.findall(after))
    sents_b, sents_a = split_sentences(b_plain), split_sentences(a_plain)
    polite_b = sum(1 for s in sents_b if POLITE_RE.search(s))
    polite_a = sum(1 for s in sents_a if POLITE_RE.search(s))
    polite_drop = polite_b >= 3 and polite_a < polite_b * 0.5

    ec_b, ec_a = len(count_ending_commas(sents_b)), len(count_ending_commas(sents_a))

    after_set = set(sents_a)
    untouched = sum(1 for s in sents_b if s in after_set)
    untouched_ratio = round(untouched / len(sents_b), 2) if sents_b else 1.0
    # 티가 없는 문장 중 손댄 비율 — 원칙 2("근거 있는 곳만") 위반 지표
    no_tell = [s for s in sents_b if not sentence_has_tell(s)]
    changed_no_tell = [s for s in no_tell if s not in after_set]
    needless_ratio = round(len(changed_no_tell) / len(no_tell), 2) if no_tell else 0.0

    warnings, aborts = [], []
    if change_rate >= 30:
        warnings.append(f"문자 변경률 {change_rate}% — 정밀 대조 필요. 수치만으로 과윤문을 판정하지 않음")
    if len_ratio < 0.8 or len_ratio > 1.2:
        warnings.append(f"길이비 {len_ratio} — 정보 누락·추가 여부를 직접 대조할 것")
    if ko_missing or ko_added:
        warnings.append(f"한글 수량 변화 (사라짐 {ko_missing}, 생김 {ko_added}) — 같은 수량인지 확인")
    if semantic_changes:
        warnings.append(f"의미 관련 표지 변화: {', '.join(semantic_changes)} — 부정·서법을 직접 대조할 것")
    if nums_missing:
        aborts.append(f"사라진 수치 {len(nums_missing)}개: {', '.join(nums_missing[:6])}")
    if nums_added:
        warnings.append(f"새로 생긴 수치 {len(nums_added)}개: {', '.join(nums_added[:6])}")
    if lat_missing:
        warnings.append(f"사라진 영문 토큰 {len(lat_missing)}개: {', '.join(lat_missing[:6])} (표준 용어를 직역했는지 확인)")
    if quotes_broken:
        warnings.append(f"따옴표 구간 누락·변경 {len(quotes_broken)}건: {quotes_broken[0][:40]} — 직접 인용이면 원문 복원")
    if quotes_added:
        warnings.append(f"새 따옴표 구간 {len(quotes_added)}건 — 발화·인용을 추가했는지 확인")
    if fn_missing or fn_added:
        aborts.append(f"각주 표지 불일치 (사라짐 {fn_missing}, 생김 {fn_added})")
    if hayeot_a > hayeot_b:
        warnings.append(f"'하였' {hayeot_b}→{hayeot_a} 증가 — 격식 상향 금지")
    if polite_drop:
        warnings.append(f"해요체·합쇼체 문장 {polite_b}→{polite_a} 급감 — register 하향 의심")
    if ec_a > ec_b:
        warnings.append(f"연결어미 뒤 쉼표 {ec_b}→{ec_a} 증가 — 윤문이 새 AI 티를 만들었다")
    if len(no_tell) >= 3 and needless_ratio > 0.5:
        warnings.append(f"티 없는 문장 {len(no_tell)}개 중 {len(changed_no_tell)}개를 손댔다 — 근거 없는 편집. 예) {changed_no_tell[0][:40]}…")
    if len_ratio > 1.8 and len(nums_added) > len(nums_missing) + 3:
        warnings.append("before/after 파일이 뒤바뀌었거나 서로 다른 문서일 수 있다 — 경로를 확인할 것")

    if aborts:
        verdict, code = "ABORT", 2
    elif warnings:
        verdict, code = "WARN", 1
    else:
        verdict, code = "PASS", 0

    return {
        "verdict": verdict, "exit_code": code,
        "change_rate_pct": change_rate, "len_ratio": len_ratio,
        "numbers_missing": nums_missing, "numbers_added": nums_added,
        "latin_missing": lat_missing, "quotes_broken": quotes_broken, "quotes_added": quotes_added,
        "korean_quantities_missing": ko_missing, "korean_quantities_added": ko_added,
        "semantic_cue_changes": semantic_changes,
        "footnotes_missing": fn_missing, "footnotes_added": fn_added,
        "hayeot_before_after": [hayeot_b, hayeot_a],
        "polite_sentences_before_after": [polite_b, polite_a],
        "ending_commas_before_after": [ec_b, ec_a],
        "untouched_sentence_ratio": untouched_ratio,
        "no_tell_sentences": len(no_tell), "needless_edit_ratio": needless_ratio,
        "sentences_before": len(sents_b), "sentences_changed": len(sents_b) - untouched,
        "needless_edit_count": len(changed_no_tell),
        "needless_edits": [x[:30] for x in changed_no_tell[:5]],
        "warnings": warnings, "aborts": aborts,
    }


def render(r: dict) -> str:
    out = [f"[{r['verdict']}] 변경률 {r['change_rate_pct']}%(글자 기준) · 길이비 {r['len_ratio']} · 손댄 문장 {r['sentences_changed']}/{r['sentences_before']} · 티 없는 문장 {r['no_tell_sentences']}개 중 손댄 것 {r['needless_edit_count']}개"]
    if r["needless_edits"]:
        out.append("  티 없이 손댄 문장: " + " | ".join(r["needless_edits"]))
    out.append(f"  연결어미 쉼표 {r['ending_commas_before_after'][0]}→{r['ending_commas_before_after'][1]} · '하였' {r['hayeot_before_after'][0]}→{r['hayeot_before_after'][1]} · 경어 문장 {r['polite_sentences_before_after'][0]}→{r['polite_sentences_before_after'][1]}")
    for a in r["aborts"]:
        out.append(f"  ✖ {a}")
    for w in r["warnings"]:
        out.append(f"  ⚠ {w}")
    if not r["aborts"] and not r["warnings"]:
        out.append("  자동 검사에서 이상 없음. 의미 보존은 별도 대조 필요")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        before = open(a.before, encoding="utf-8").read()
        after = open(a.after, encoding="utf-8").read()
    except OSError as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return 3
    if not before.strip() or not after.strip():
        print("입력 오류: 빈 파일", file=sys.stderr)
        return 3
    r = check(before, after)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else render(r))
    return r["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
