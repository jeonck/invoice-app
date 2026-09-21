# Google 로그인 · Google Drive 저장 설정

이 앱은 **Google 로그인**으로 접근을 통제하고, 선택적으로 **생성한 인보이스를
로그인한 본인의 Google Drive에 저장**합니다. 둘 다 같은 OAuth 클라이언트 하나를
쓰기 때문에 설정은 한 번에 끝납니다.

처음 설정하면 10~15분 정도 걸립니다. 순서대로 따라가시면 됩니다.

> 콘솔 UI 명칭은 자주 바뀝니다. 아래는 현재 명칭과 이전 명칭을 함께 적었으니,
> 화면에 보이는 쪽을 따라가시면 됩니다.

---

## 0. 먼저 확인할 것

앱이 실제로 서비스되는 **주소**를 확정하세요. 리디렉션 URI에 정확히 이 주소를
등록해야 하고, 하나라도 다르면 로그인이 실패합니다.

| 실행 위치 | 앱 주소 | 리디렉션 URI |
| --- | --- | --- |
| 로컬 | `http://localhost:8501` | `http://localhost:8501/oauth2callback` |
| Streamlit Cloud | `https://<앱이름>.streamlit.app` | `https://<앱이름>.streamlit.app/oauth2callback` |

로컬과 배포본을 모두 쓴다면 **두 개 다** 등록하면 됩니다.

---

## 1. Google Cloud 프로젝트 만들기

[Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 새로
만들거나 기존 것을 고릅니다. 개인 용도면 이름은 무엇이든 상관없습니다.

이후 모든 단계는 **같은 프로젝트 안에서** 진행해야 합니다.

## 2. Google Drive API 활성화 (Drive 저장을 쓸 때만)

**API 및 서비스 → 라이브러리**에서 `Google Drive API`를 검색해 **사용 설정**을
누릅니다.

로그인만 쓸 거라면 이 단계는 건너뛰어도 됩니다. 나중에 Drive 저장을 켤 때
활성화하지 않으면, 저장 시 실패합니다.

## 3. OAuth 동의 화면 구성

**API 및 서비스 → OAuth 동의 화면** (최근 콘솔에서는 **Google 인증 플랫폼**).

- **사용자 유형(User type)**
  - 개인 Gmail 계정: **외부(External)** — 선택지가 이것뿐입니다
  - Google Workspace 조직 계정: **내부(Internal)** 를 고르면 조직 구성원만
    로그인할 수 있게 되어, 5단계의 테스트 사용자 문제가 아예 생기지 않습니다
- **앱 이름 / 지원 이메일 / 개발자 연락처**를 채웁니다. 앱 이름은 로그인할 때
  동의 화면에 그대로 보이므로 알아볼 수 있는 이름으로 하세요.

## 4. 스코프(권한) 추가

같은 화면의 **데이터 액세스(Data Access)** — 이전 명칭은 **범위(Scopes)** —
에서 다음을 추가합니다.

| 스코프 | 용도 | 분류 |
| --- | --- | --- |
| `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` | 로그인, 이메일 확인 | 비민감 |
| `https://www.googleapis.com/auth/drive.file` | Drive 저장 | 비민감 |

`drive.file`은 **이 앱이 만든 파일만** 접근할 수 있는 좁은 스코프입니다. 기존
Drive의 다른 파일은 읽지도 보지도 못합니다. 네 개 모두 **비민감(non-sensitive)**
스코프라, 구글 검토(verification)를 받지 않아도 됩니다.

## 5. 테스트 사용자 추가 또는 앱 게시 — 여기서 많이 막힙니다

**대상(Audience)** 화면의 **게시 상태**를 확인하세요. 새로 만든 앱은 **테스트
(Testing)** 상태이고, 이 상태에서는 등록된 테스터만 로그인할 수 있습니다.
그렇지 않으면 이 화면을 보게 됩니다.

```
403 오류: access_denied
앱은 현재 테스트 중이며 개발자가 승인한 테스터만 앱에 액세스할 수 있습니다.
```

둘 중 하나로 해결합니다.

- **테스트 사용자에 추가** — **대상 → 테스트 사용자 → 사용자 추가**에 본인
  이메일을 넣습니다. 즉시 적용되고, 최대 100명까지 등록됩니다.
- **앱 게시(Publish app)** — 같은 화면의 버튼. 4단계의 스코프가 전부 비민감이라
  검토 없이 바로 게시됩니다.

**게시해도 아무나 쓸 수 있게 되는 것은 아닙니다.** 실제 접근 통제는 앱의
`allowed_emails` 목록이 담당합니다 (8단계).

테스트 상태에서는 동의 화면에 "확인되지 않은 앱" 경고가 뜰 수 있습니다.
**고급 → (앱 이름)(으)로 이동**을 누르면 진행됩니다.

## 6. OAuth 클라이언트 ID 만들기

**API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**
(최근 콘솔에서는 **클라이언트 → 클라이언트 만들기**).

- **애플리케이션 유형**: `웹 애플리케이션`
- **승인된 리디렉션 URI**: 0단계 표의 URI를 **그대로** 추가합니다

주의할 점:

- 경로는 반드시 `/oauth2callback` 입니다
- `http` / `https`, 끝의 슬래시, 포트 번호까지 **정확히** 일치해야 합니다.
  다르면 `redirect_uri_mismatch`가 납니다
- "승인된 **자바스크립트 원본**"이 아니라 "승인된 **리디렉션 URI**" 칸입니다

생성되면 **클라이언트 ID**와 **클라이언트 보안 비밀번호**가 나옵니다. 다음
단계에서 씁니다.

## 7. cookie_secret 만들기

Streamlit이 로그인 쿠키에 서명할 때 쓰는 값입니다. 아무 문자열이나 넣지 말고
난수로 만드세요.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 8. Streamlit secrets 작성

로컬은 `.streamlit/secrets.toml` 파일에, Streamlit Community Cloud는 앱의
**Settings → Secrets** 에 붙여넣습니다. 아래가 **로그인 + Drive 저장**을 모두
켠 완성본입니다.

```toml
[auth]
redirect_uri = "https://<앱이름>.streamlit.app/oauth2callback"
cookie_secret = "<7단계에서 만든 난수>"
expose_tokens = ["access"]                 # Drive 저장에 필요

[auth.google]
client_id = "<...>.apps.googleusercontent.com"
client_secret = "<...>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
client_kwargs = { scope = "openid email profile https://www.googleapis.com/auth/drive.file" }

[app_auth]
allowed_emails = ["you@example.com"]       # 실제로 이 앱을 쓸 사람
# 또는, 방문자 누구나 쓰게 하려면 위 줄 대신:
# allow_any_google_account = true
```

핵심만 짚으면:

- **`redirect_uri`는 6단계에 등록한 값과 글자 단위로 같아야 합니다.** 로컬에서
  실행할 때는 `http://localhost:8501/oauth2callback`으로 바꿔야 합니다
- **사용 대상 설정이 실제 접근 통제입니다.** Google 로그인은 "이 사람이 그
  구글 계정의 주인"임만 증명할 뿐, 누구나 로그인 자체는 성공합니다. 특정 인원만
  쓰게 하려면 `allowed_emails`, 방문자 누구나 쓰게 하려면
  `allow_any_google_account = true`. 둘 다 없으면 앱은 아무도 들여보내지 않고
  잠깁니다 — 여는 것은 명시적인 결정이어야 하니까요. 어느 쪽이든 인보이스는
  각자의 Drive에 저장되므로, 열어도 남의 계좌정보를 내가 떠안지 않습니다
- **Drive 저장을 안 쓸 거면** `expose_tokens`와 `client_kwargs` 두 줄을 빼면
  됩니다. 저장 버튼이 비활성 상태가 되고 나머지는 그대로 동작합니다
- `.streamlit/secrets.toml`은 `.gitignore`에 들어 있습니다. 커밋하지 마세요

## 9. 동작 확인

1. 앱을 열면 **로그인 화면**만 보입니다 (인보이스 폼은 렌더링되지 않습니다)
2. **Google 계정으로 로그인** → 동의 화면에서 계정 선택
3. Drive 저장을 켰다면 동의 항목에
   **"Google Drive의 이 앱에서 만든 파일 보기 및 관리"** 가 보여야 합니다.
   안 보이면 `client_kwargs`의 스코프가 적용되지 않은 것입니다
4. 사이드바에 로그인한 이메일과 **로그아웃** 버튼이 보이면 성공입니다
5. 인보이스를 만들고 **Google Drive에 저장**을 누르면 본인 Drive의
   `Invoices/<연도>/` 아래에 `INV-....pdf` 와 `INV-....json` 이 생깁니다

> **스코프를 나중에 추가했다면 반드시 로그아웃 후 다시 로그인하세요.** 기존
> 로그인 쿠키에는 예전 스코프의 토큰이 들어 있어서, 그대로 두면 Drive 저장이
> 계속 실패합니다.

---

## 문제 해결

| 증상 | 원인과 해결 |
| --- | --- |
| `403: access_denied` — "개발자가 승인한 테스터만" | 5단계. 테스트 사용자에 본인 계정을 추가하거나 앱을 게시 |
| `redirect_uri_mismatch` | 6단계의 등록 URI와 `redirect_uri`가 다름. 스킴·포트·끝 슬래시·`/oauth2callback` 경로까지 대조 |
| `invalid_client` | `client_id` / `client_secret` 오타, 또는 다른 프로젝트의 값을 넣음 |
| `No module named 'httpx'` | `streamlit[auth]`가 아니라 `streamlit`만 설치됨. `pip install -r requirements.txt` |
| "Google 로그인 설정이 필요합니다" 화면 | secrets의 `[auth]` / `[auth.google]` 누락 또는 오타. Cloud에서는 저장 후 **Reboot app** |
| "허용 계정 목록이 비어 있습니다" 화면 | `[app_auth] allowed_emails`가 비어 있음 |
| 로그인은 되는데 "사용 권한이 없습니다" | 로그인한 이메일이 `allowed_emails`에 없음 (대소문자는 무시하므로 철자 확인) |
| 저장 버튼이 계속 비활성 | `expose_tokens = ["access"]` 누락, 또는 스코프 추가 후 재로그인을 안 함 |
| "Drive 접근 권한이 만료되었습니다" | 액세스 토큰은 1시간쯤 뒤 만료되고 Streamlit이 갱신하지 않음. 로그아웃 후 재로그인 |
| 저장 시 Drive API 오류 | 2단계의 Google Drive API 사용 설정 누락 |

## 보안 관점에서 알아둘 것

- **앱은 구글 자격증명을 하나도 보관하지 않습니다.** Drive 저장은 이미 이뤄진
  로그인의 액세스 토큰을 빌려 쓰므로, 파일은 만든 사람 본인 Drive에 그 사람
  명의로 생성됩니다. 권한은 [Google 계정 → 보안 → 타사 앱](https://myaccount.google.com/connections)
  에서 언제든 직접 회수할 수 있습니다
- **`drive.file`은 앱이 만든 파일로 범위가 제한됩니다.** 이 앱은 기존 Drive
  내용을 열람할 수 없습니다
- **접근 통제는 `allowed_emails`입니다.** 앱 게시 여부나 테스트 사용자 설정이
  아니라 이 목록이 실제 문지기입니다
- 저장된 PDF와 JSON에는 **입력한 계좌정보가 그대로 들어 있습니다.** 그 Drive
  폴더는 인보이스 원본과 같은 수준으로 취급하세요
