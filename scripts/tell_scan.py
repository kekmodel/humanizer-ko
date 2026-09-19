#!/usr/bin/env python3
"""tell_scan.py — 한국어 텍스트의 'AI 티·번역투' 결정적 사전 스캔.

표준 라이브러리만 사용. 판정이 아니라 *카운트*를 돌려준다.
LLM이 윤문 전에 어디를 봐야 하는지, 윤문 후에 무엇이 줄었는지 확인하는 용도.

사용:
    python3 tell_scan.py input.txt            # 사람이 읽는 요약
    python3 tell_scan.py input.txt --json     # JSON
    python3 tell_scan.py input.txt --strip-frame before.txt   # 챗봇 머리·꼬리 프레임을 벗겨 before.txt로 저장 후 스캔
    cat input.txt | python3 tell_scan.py -    # stdin

설계 원칙
- 정밀도(precision) 우선. 사람 글에도 흔한 표현은 '밀집'만 센다.
- 단일 지표로 문서를 판정하지 않는다. 모든 수치는 참고값이다.
- 연결어미 뒤 쉼표는 형태소 분석 없이 음절로 잡으므로 근사치다. 접속부사·명사
  ('그리고,' '최고,' '참고,')는 제외 목록으로 걸러낸다.
"""
import json
import re
import statistics
import sys

# ---------------------------------------------------------------- 문장 분리
_SENT_END = re.compile(r"(?<=[.!?。])\s+|(?<=[다요죠까네])\.\s*\n|\n{2,}")


def split_sentences(text: str):
    text = text.replace("\r\n", "\n")
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # 마크다운 헤딩·불릿 기호 제거 후 판단
        core = re.sub(r"^(#{1,6}\s+|[-*•]\s+|\d+[.)]\s+)", "", p)
        if core:
            out.append(core)
    return out


def split_paragraphs(text: str):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# ---------------------------------------------------------------- 패턴 정의
# (키, 설명, 정규식, 근거등급)  근거등급: 3=실증 강함, 2=번역투 문헌+정밀도 높음, 1=문체 정리
HIGH_PRECISION = [
    ("double_passive", "이중 피동 (되어지다·지게 되다)", r"되어\s?(지|진|질|졌)|지게\s?(되|된|될)", 2),
    ("by_passive", "'~에 의해' 피동", r"에\s?의해(서)?", 2),
    ("have_literal", "'가지고 있다' 직역", r"가지고\s?있", 2),
    ("double_particle", "이중 조사 (~에서의·~으로의…)", r"(에서의|에로의|으로의|에의|으로부터의|로부터의)", 2),
    ("e_isseo", "'~에 있어(서)'", r"에\s?있어(서)?(?=\s|,|는)", 2),
    ("contrast_parallel", "부정 대구 'A가 아니라 B' 계열 (C-8, 처방 기준 2회+)", r"(이|가|은|는|것이|것은)\s?아니(라|다|며|고)\b|(이|가)\s?아닌\s|인가,\s?[^.]{1,40}인가", 3),
    ("range_lift", "범위 상승 '단순한 X를 넘어 Y'", r"(단순한|단순히|단지)\s?[^.]{1,30}(을|를)\s?넘어", 1),
    ("no_longer", "'더 이상 ~ 아니다/않다'", r"더\s?이상\s?[^.]{0,30}(아니|않)", 1),
    ("cleft", "분열문 '핵심은/문제는/중요한 것은 ~이다' (2회+)", r"(핵심|문제|관건|답|중요한 것|필요한 것)(은|는)\s", 1),
    ("reason_inversion", "도치 결산 '~하는 이유다'", r"(하는|인|되는|없는|있는)\s?이유(다|이다|입니다)", 1),
    ("conclusion_lexicon", "결산 라벨 (결론적으로·요약하면·정리하자면·종합하면; 마지막 문단 첫머리면 1회도 삭제)", r"결론적으로|요약하면|정리하자면|종합하면|요컨대", 1),
    ("enumeration_formula", "기계적 열거 '첫째/둘째/셋째' (2회+면 처방)", r"(첫째|둘째|셋째|넷째|첫\s?번째로|두\s?번째로|세\s?번째로)[,\s]", 1),
    ("significance_inflation", "의의 과장 (시사하는 바가 크다·주목할 만하다…)", r"시사하는\s?바|주목할\s?만|간과할\s?수\s?없|무시할\s?수\s?없|의미가\s?크|의미심장", 1),
    ("list_intro", "열거 도입 (크게 세 가지·다음과 같은)", r"크게\s?(두|세|네|다섯)\s?가지|다음과\s?같(은|이)", 1),
    ("vague_horizon", "결말부 막연한 시간지평 (향후·앞으로·중장기적으로)", r"^(향후|앞으로|중장기적으로|장기적으로)", 1),
    ("empty_caveat", "내용 없는 반론 슬롯 (과제도 남아 있다…)", r"(과제|한계|아쉬운\s?점|우려)(도|는)\s?(남아|분명|있다|존재)", 1),
    ("hedge_stack", "이중·삼중 완곡", r"(있을\s?수\s?있|있을\s?것으로\s?보|보여질\s?수|될\s?수\s?있을\s?것)", 1),
    ("chatbot_frame", "챗봇 잔재 (물론입니다·다음은 ~입니다·도움이 되셨길; 블로그의 '댓글로 남겨주세요'는 정상)", r"^(물론입니다|네,|알겠습니다|다음은\s.+입니다:?$)|도움이\s?되셨|추가\s?질문이\s?있으시면\s?(말씀|언제든)|더\s?궁금한\s?점이\s?있으시면\s?(말씀|언제든)", 1),
    ("policy_verbs", "범용 정책동사 (확대·강화·개선·확보·마련·구축, 문단 3회+)", r"(확대|강화|개선|확보|마련|구축)(하|해|되|될|한|할)", 3),
    ("abstract_chain", "'~적 N' 추상 체인 (3회+)", r"[가-힣]{1,4}적\s[가-힣]{1,4}(을|를|이|가|은|는|의|에)", 3),
    ("pronoun_3p", "3인칭 대명사 (그는·그녀·그들, 문맥 조건으로 판단)", r"(^|\s)(그는|그녀|그들|그의|그것은|그것이)(\s|$)", 2),
]

CONNECTIVE_ENDINGS = ("고", "며", "지만", "면서", "는데", "아서", "어서", "여서", "해서", "려면", "다면", "으며", "으나", "나")
# 연결어미 음절로 끝나지만 어미가 아닌 단어(접속부사·명사·부사). 뒤에 쉼표가 와도 세지 않는다.
COMMA_EXCLUDE = {
    "그리고", "하지만", "그렇지만", "그러면서", "그런데", "그러나", "또는", "혹은", "및",
    "사고", "최고", "참고", "비고", "창고", "재고", "광고", "보고", "경고", "원고", "피고",
    "신고", "예고", "선고", "고", "친구", "물고", "내고", "만고", "회고", "권고", "충고",
    "그러니", "먼저", "한편", "반면", "게다가", "더구나", "아울러", "이어",
}
SENTENCE_INITIAL_CONJ = re.compile(r"^(또한|따라서|즉|나아가|아울러|게다가|더욱이|그러나|하지만|그런데|이는|이처럼|이러한|이와\s?같이)\b")
DEONTIC_END = re.compile(r"(해야\s?(한다|합니다|할\s?것이다)|필요가\s?있다|필요하다|요구된다|마련해야|시급하다)[.!]?\s*$")
HUMAN_MARKERS = re.compile(r"솔직히|내가\s?보기|모르겠지만|당시|힘들|또,|글쎄|사실은")


_TELL_RES = None


def sentence_has_tell(sentence: str) -> bool:
    """이 문장에 룰북 패턴이 하나라도 있는가 (fidelity_check의 '티 없는데 손댄 문장' 판정용)."""
    global _TELL_RES
    if _TELL_RES is None:
        _TELL_RES = [re.compile(rx, re.M) for _, _, rx, _ in HIGH_PRECISION]
        _TELL_RES += [re.compile(r"(에\s?대해|를\s?통해|을\s?통해|할\s?수\s?있|것이다|되고\s?있|지고\s?있|라고\s?할\s?수|라고\s?볼\s?수|[가-힣]+적\s|[가-힣]+성의\s|매우|정말|상당히)")]
    if any(r.search(sentence) for r in _TELL_RES):
        return True
    if count_ending_commas([sentence]):
        return True
    if SENTENCE_INITIAL_CONJ.search(sentence) or DEONTIC_END.search(sentence):
        return True
    return False


def count_ending_commas(sentences):
    hits = []
    for s in sentences:
        for m in re.finditer(r"([가-힣]+)\s?,", s):
            word = m.group(1)
            if word in COMMA_EXCLUDE or len(word) < 2:
                continue
            if word.endswith(CONNECTIVE_ENDINGS):
                # '나'로 끝나는 명사(하나, 언제나)·조사 결합 오검출 완화
                if word.endswith("나") and not word.endswith(("으나", "거나", "지나")):
                    continue
                hits.append(word + ",")
    return hits


# 전체 문단이 명확한 인사인 경우만 제거한다. 본문과 섞인 문단은 남긴다.
FRAME_HEAD = re.compile(r"(?:물론입니다|알겠습니다|좋습니다|네)[.!！]?|네,")
FRAME_TAIL = re.compile(r"(?:도움이 되셨길 바랍니다|도움이 되었길 바랍니다)[.!！]?")


def strip_frame(text: str) -> str:
    """확실한 독립 인사만 제거하고 나머지 본문·공백을 원형 보존한다."""
    parts = re.split(r"(\r?\n[ \t]*\r?\n)", text)
    start, end = 0, len(parts)
    # 최소 한 문단을 남긴다. 애매하거나 본문과 같은 문단이면 직접 판단한다.
    while start + 2 < end and FRAME_HEAD.fullmatch(parts[start].strip()):
        start += 2
    while end - 2 > start and FRAME_TAIL.fullmatch(parts[end - 1].strip()):
        end -= 2
    return "".join(parts[start:end])


def scan(text: str) -> dict:
    sentences = split_sentences(text)
    paragraphs = split_paragraphs(text)
    n_chars = len(re.sub(r"\s", "", text))
    lengths = [len(s) for s in sentences]

    result = {
        "chars_no_space": n_chars,
        "sentences": len(sentences),
        "paragraphs": len(paragraphs),
        "avg_sentence_len": round(statistics.mean(lengths), 1) if lengths else 0,
        "sentence_len_stdev": round(statistics.pstdev(lengths), 1) if len(lengths) > 1 else 0,
        "long_sentences_100plus": sum(1 for l in lengths if l >= 100),
        "patterns": {},
        "structure": {},
        "human_markers": len(HUMAN_MARKERS.findall(text)),
    }

    for key, label, rx, grade in HIGH_PRECISION:
        flags = re.M
        matches = [m.group(0).strip() for m in re.finditer(rx, text, flags)]
        if matches:
            result["patterns"][key] = {
                "label": label, "count": len(matches), "grade": grade,
                "examples": matches[:4],
            }

    # 연결어미 뒤 쉼표 (C-11) — 근사치
    commas = count_ending_commas(sentences)
    result["structure"]["ending_comma"] = {
        "label": "연결어미 뒤 쉼표 (근사치, 6회+ 또는 문장의 40%+ 이면 강한 신호)",
        "count": len(commas),
        "per_sentence": round(len(commas) / len(sentences), 2) if sentences else 0,
        "examples": commas[:6], "grade": 3,
    }

    # 문두 접속사 — 문단 내 밀집만 의미 있음 (H-1/H-3: 3회+/문단)
    dense_paras = 0
    max_in_para = 0
    for p in paragraphs:
        c = sum(1 for s in split_sentences(p) if SENTENCE_INITIAL_CONJ.search(s))
        max_in_para = max(max_in_para, c)
        if c >= 3:
            dense_paras += 1
    result["structure"]["initial_conjunction"] = {
        "label": "문두 접속사·메타 진입 (한 문단 3회+ 밀집만 처방 대상)",
        "max_per_paragraph": max_in_para, "dense_paragraphs": dense_paras, "grade": 1,
    }

    # 동일 종결 연속 (E-2)
    runs, cur, prev = 0, 1, None
    for s in sentences:
        tail = re.sub(r"[.!?\"'”’)\]]+$", "", s)[-2:]
        if tail == prev:
            cur += 1
        else:
            if cur >= 4:
                runs += 1
            cur = 1
        prev = tail
    if cur >= 4:
        runs += 1
    result["structure"]["same_ending_runs_4plus"] = {"label": "동일 종결어미 4문장+ 연속 구간 수", "count": runs, "grade": 1}

    # 당위로 끝나는 문단 (I-4)
    deontic = sum(1 for p in paragraphs if DEONTIC_END.search(p))
    result["structure"]["deontic_paragraph_endings"] = {
        "label": "당위('해야 한다')로 끝나는 문단 수 (2개+면 이동 처방)", "count": deontic, "grade": 3,
    }

    # 서식 (C·J)
    result["structure"]["markdown"] = {
        "headings": len(re.findall(r"^#{1,6}\s", text, re.M)),
        "bullets": len(re.findall(r"^\s*[-*•]\s", text, re.M)),
        "numbered": len(re.findall(r"^\s*\d+[.)]\s", text, re.M)),
        "bold": len(re.findall(r"\*\*[^*]+\*\*", text)),
        "emoji": len(re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", text)),
        "em_dash": text.count("—"),
        "quote_pairs": len(re.findall(r"[\"“][^\"”]{2,}[\"”]", text)),
        "paren_english": len(re.findall(r"\([A-Za-z][A-Za-z\s\-]{1,}\)", text)),
    }

    # 밀도와 모드 제안 — 판정이 아니라 출발점
    # 사람 글에도 1~2회는 흔한 패턴은 '반복'부터 센다 (C-8 2회+, 정책동사 3회+, 추상체인 3회+, 대명사 3회+)
    repeat_floor = {"contrast_parallel": 2, "policy_verbs": 3, "abstract_chain": 3, "pronoun_3p": 3,
                    "cleft": 2, "conclusion_lexicon": 2, "enumeration_formula": 2}
    weighted = 0.0
    for k, v in result["patterns"].items():
        if v["count"] < repeat_floor.get(k, 1):
            continue
        weighted += v["count"] * (1.5 if v["grade"] == 3 else 1.0 if v["grade"] == 2 else 0.5)
    ec = result["structure"]["ending_comma"]
    if ec["count"] >= 6 or (ec["per_sentence"] >= 0.4 and len(sentences) >= 5):
        weighted += 3
    if deontic >= 2:
        weighted += deontic
    if dense_paras:
        weighted += dense_paras
    density = round(weighted / n_chars * 1000, 2) if n_chars else 0
    result["tell_weight"] = round(weighted, 1)
    result["tell_density_per_1000"] = density
    if weighted < 3 or density < 2:
        mode = "light"
    elif density >= 8 and weighted >= 12 and n_chars >= 1500:
        mode = "heavy"
    else:
        mode = "standard"
    if n_chars > 12000 and mode != "light":
        mode = "heavy"
    result["long_sentence_note"] = (
        "장문 부재(E-1)는 800자 이상 논설문에서만 신호" if n_chars < 800 and result["long_sentences_100plus"] == 0
        else ("100자+ 장문 없음 — E-1 후보(인접 문장 잇기, 내용 추가 금지)" if result["long_sentences_100plus"] == 0 else "")
    )
    result["suggested_mode"] = mode
    return result


def render(r: dict) -> str:
    lines = []
    lines.append(f"글자수(공백 제외) {r['chars_no_space']} · 문장 {r['sentences']} · 문단 {r['paragraphs']}")
    lines.append(f"평균 문장 길이 {r['avg_sentence_len']} · 표준편차 {r['sentence_len_stdev']} · 100자+ 장문 {r['long_sentences_100plus']}개" + (f"  ({r['long_sentence_note']})" if r.get('long_sentence_note') else ""))
    lines.append(f"티 가중합 {r['tell_weight']} · 밀도 {r['tell_density_per_1000']}/1000자 → 제안 모드: {r['suggested_mode']}  (사용자 명시가 우선, 이 수치는 판정이 아니라 출발점)")
    if r["human_markers"]:
        lines.append(f"사람 글 표지 {r['human_markers']}건 감지 — 보존 대상(솔직히·당시·힘들다·'또,' 등)")
    lines.append("")
    lines.append("[어휘·구문 패턴]  ★★★ 실증 강함 · ★★ 번역투 문헌 · ★ 문체 정리(밀집 시만)")
    if not r["patterns"]:
        lines.append("  (없음)")
    for k, v in sorted(r["patterns"].items(), key=lambda kv: (-kv[1]["grade"], -kv[1]["count"])):
        stars = "★" * v["grade"]
        ex = " / ".join(v["examples"])
        lines.append(f"  {stars:<3} {v['label']}: {v['count']}회  예) {ex}")
    lines.append("")
    lines.append("[구조]")
    s = r["structure"]
    ec = s["ending_comma"]
    lines.append(f"  ★★★ 연결어미 뒤 쉼표: {ec['count']}회 (문장당 {ec['per_sentence']})  예) {' '.join(ec['examples'])}")
    ic = s["initial_conjunction"]
    lines.append(f"  ★   문두 접속사 최대 {ic['max_per_paragraph']}회/문단, 밀집 문단 {ic['dense_paragraphs']}개")
    lines.append(f"  ★   동일 종결 4연속 구간: {s['same_ending_runs_4plus']['count']}개")
    lines.append(f"  ★★★ 당위로 끝나는 문단: {s['deontic_paragraph_endings']['count']}개")
    md = s["markdown"]
    lines.append(f"  서식: 헤딩 {md['headings']} · 불릿 {md['bullets']} · 번호목록 {md['numbered']} · 볼드 {md['bold']} · 이모지 {md['emoji']} · 대시 {md['em_dash']} · 따옴표쌍 {md['quote_pairs']} · 영어괄호 {md['paren_english']}")
    return "\n".join(lines)


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    src = argv[1]
    text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    if "--strip-frame" in argv:
        # --strip-frame OUT : 프레임을 벗긴 본문을 OUT에 쓰고, 그 본문을 스캔한다
        i = argv.index("--strip-frame")
        out = argv[i + 1] if i + 1 < len(argv) else None
        stripped = strip_frame(text)
        if out and not out.startswith("--"):
            open(out, "w", encoding="utf-8").write(stripped)
            print(f"[프레임 제거] {len(text)}자 → {len(stripped)}자, 저장: {out}")
        text = stripped
    r = scan(text)
    if "--json" in argv:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(render(r))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
