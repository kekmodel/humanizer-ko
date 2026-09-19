# humanizer-ko

AI가 쓴 한국어 글의 AI 티·번역투를 내용 불변으로 고치는 스킬. Claude Code와 OpenAI Codex CLI에서 같은 폴더를 그대로 쓴다.

## 다른 컴퓨터에 설치 (Codex)

Git과 GitHub CLI가 필요합니다. 비공개 저장소이므로 접근 권한이 있는 GitHub 계정으로 로그인한 뒤 설치합니다.

```bash
gh auth login
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
gh repo clone kekmodel/humanizer-ko "${CODEX_HOME:-$HOME/.codex}/skills/humanizer-ko"
```

대상 폴더가 이미 있으면 덮어쓰지 말고 기존 파일을 백업한 뒤 설치하세요. 위 명령으로 설치한 복제본은 다음 명령으로 업데이트할 수 있습니다.

```bash
git -C "${CODEX_HOME:-$HOME/.codex}/skills/humanizer-ko" pull --ff-only
```

새 메시지에서 `$humanizer-ko`로 호출하고 다듬을 글을 함께 입력합니다. 스킬이 나타나지 않으면 새 작업을 열어 확인하세요.

예시:

- `$humanizer-ko 이 글을 light 모드로 다듬어줘: ...`
- `$humanizer-ko 최소한으로 수정하고 정밀 검수해줘: ...`
- `$humanizer-ko 이 글을 heavy 모드로 다듬어줘: ...`

Python 3 표준 라이브러리만 사용합니다. Python이 없으면 자동 검사 대신 원문과 결과를 직접 대조합니다.

Claude Code에서도 같은 폴더를 `~/.claude/skills/humanizer-ko`에 복제해 `/humanizer-ko`로 사용할 수 있습니다.

## 구성

```
humanizer-ko/
├── SKILL.md                 # 원칙 7 + 절차 + 출력 형식 (모델이 항상 읽는 부분)
├── references/
│   ├── rules.md             # 패턴 룰북. 근거 등급 ★★★/★★/★ 와 밀집 조건
│   └── examples.md          # before→after 예시, 과윤문 반례, 손대지 말아야 할 글
└── scripts/
    ├── tell_scan.py         # 윤문 전 결정적 스캔 (카운트·모드 제안)
    └── fidelity_check.py    # 윤문 후 자동 대조 (exit 0/1/2/3; 의미 보존 보증 아님)
```

## 설계 방침

- 판단은 모델이 한다. 스크립트는 세고 대조할 뿐 판정하지 않는다.
- 패턴은 근거 강도로 선별했다. 실증이 없거나 사람이 더 쓰는 표현("~를 통해", "것이다", 문두 접속사, hype 어휘)은 밀집 조건에서만 처방한다.
- 정량 위험도 점수·베이스라인·서브에이전트 파이프라인은 두지 않았다. 검증 불가능한 숫자보다 길이비·수치 집합·인용 verbatim 같은 결정적 검사를 택했다.
- 워터마크 제거 기능은 없고, "탐지기 우회"를 목표로 하지 않는다.

## 출처와 라이선스

MIT. 패턴 분류와 처방 문법은 [epoko77-ai/im-not-ai](https://github.com/epoko77-ai/im-not-ai) (MIT) 의 taxonomy·quick-rules·empirical-validation 문서를 검토해 근거가 확인된 항목만 재구성했다. 연결어미 뒤 쉼표 근거는 Park et al., *KatFishNet* (ACL 2025). 번역투 항목은 김순영(2012), 『새국어생활』 등 국립국어원·번역학 문헌.

## 모드와 검수

light는 최소 수정, standard는 주요 패턴 수정, heavy는 standard 수정과 전체 정밀 검수를 묶은 모드다. `light + 정밀 검수`처럼 따로 지정할 수 있다. 변경률은 참고값이며 30% 이상이면 정밀 대조한다.

자동 검사 PASS는 감지된 이상이 없다는 뜻이다. 주체·부정·조건·서법·시점·수량·인과관계는 별도로 대조한다.

회귀 검증: 스킬 디렉터리에서 `python3 -B -m unittest discover -s scripts/tests -v`.
