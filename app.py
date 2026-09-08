import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore, storage
import json
from datetime import datetime, timedelta
import streamlit.components.v1 as components
import base64  # 🔐 구글 ID 토큰 해독용
from streamlit_oauth import OAuth2Component  # 🔐 구글 OAuth 로그인용
import io          # 엑셀 파일 생성용
import xlsxwriter  # 엑셀 파일 생성 및 이미지 삽입용
import requests    # 이미지 다운로드용
from PIL import Image  # 🖼️ 이미지 실제 크기 계산 및 자동 축소용
from PIL.ExifTags import TAGS, GPSTAGS  # 🔧 사진 GPS 좌표 추출용
import re  # 🔧 지도 URL에서 좌표 파싱용
from urllib.parse import quote  # 🔧 카카오맵 검색 링크용 URL 인코딩

# 🏢 페이지 기본 설정
st.set_page_config(page_title="대구공공시설관리공단 시설관리팀 운영 웹", layout="wide")

# 🔄 st.data_editor 강제 리프레시를 위한 버전 관리 세션 상태 초기화
if "table_version" not in st.session_state:
    st.session_state.table_version = 0

# ---------------------------------------------------------
# 🛡️ [보안 강화] 이중 보안 시스템: 1차 구글 로그인 + 2차 비밀번호 인증
if "google_auth" not in st.session_state:
    st.session_state.google_auth = False
if "pw_auth" not in st.session_state:
    st.session_state.pw_auth = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = st.secrets.get("REDIRECT_URI")

# 🚨 구글 로그인 400 에러 방지용 안전장치
if not CLIENT_ID or not REDIRECT_URI:
    st.error("🚨 Streamlit Secrets(비밀키)를 읽어오지 못했습니다. 앱 우측 하단의 Settings -> Secrets 설정이 지워지지 않았는지 확인해 주세요.")
    st.stop()

# 구글 인증과 비밀번호 인증이 둘 다 통과되어야만 메인 화면이 열립니다.
if not (st.session_state.google_auth and st.session_state.pw_auth):
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])

    with col2:
        st.title("🔒 시설관리팀 운영 웹")
        st.markdown("---")

        # [1단계] 구글 계정 인증 단계
        if not st.session_state.google_auth:
            st.info("📢 1단계: 업무용 구글 계정으로 인증해주세요.")

            oauth2 = OAuth2Component(
                CLIENT_ID, CLIENT_SECRET,
                "https://accounts.google.com/o/oauth2/v2/auth",
                "https://oauth2.googleapis.com/token",
                "https://oauth2.googleapis.com/token",
                "https://oauth2.googleapis.com/revoke"
            )

            result = oauth2.authorize_button(
                name="Google 계정으로 계속하기",
                icon="https://www.google.com/favicon.ico",
                redirect_uri=REDIRECT_URI,
                scope="openid email profile",
                key="google_login",
                use_container_width=True
            )

            if result:
                id_token = result.get("token", {}).get("id_token")
                if id_token:
                    payload = id_token.split(".")[1]
                    payload += "=" * ((4 - len(payload) % 4) % 4)
                    decoded_payload = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
                    user_email = decoded_payload.get("email")

                    # 🎯 허가된 팀원 구글 이메일 명단 (화이트리스트)
                    allowed_emails = [
                        "sisul2026.qr@gmail.com",  # 본인 계정
                    ]

                    if user_email in allowed_emails:
                        st.session_state.user_email = user_email
                        st.session_state.google_auth = True
                        st.rerun()
                    else:
                        st.error(f"❌ 접속 권한이 없는 이메일 계정입니다. ({user_email})")

        # [2단계] 구글 인증 완료 후 비밀번호 입력 단계
        elif not st.session_state.pw_auth:
            st.success(f"👤 {st.session_state.user_email} 님, 1차 인증 성공")
            st.info("🔑 2단계: 시설관리팀 운영 비밀번호를 입력해주세요.")

            with st.form("pw_form"):
                password = st.text_input("비밀번호", type="password", placeholder="비밀번호 입력")
                if st.form_submit_button("최종 웹 접속하기", use_container_width=True):
                    if password == "sisul123!":
                        st.session_state.pw_auth = True
                        st.success("✅ 이중 인증 완료! 잠시 후 화면을 불러옵니다...")
                        st.rerun()
                    else:
                        st.error("❌ 비밀번호가 일치하지 않습니다.")

    st.stop()
# ---------------------------------------------------------

# 🛡️ [단축키 방패] C키 팝업 창 방지
components.html(
    """
    <script>
    function blockCacheShortcut(e) {
        if (e.key === 'c' || e.key === 'C') {
            const activeTag = window.parent.document.activeElement ? window.parent.document.activeElement.tagName.toLowerCase() : '';
            if (activeTag === 'input' || activeTag === 'textarea') return;
            if (e.ctrlKey || e.metaKey) return;

            e.stopImmediatePropagation();
            e.stopPropagation();
            e.preventDefault();
        }
    }
    window.parent.document.addEventListener('keydown', blockCacheShortcut, true);
    window.parent.document.addEventListener('keypress', blockCacheShortcut, true);
    window.parent.document.addEventListener('keyup', blockCacheShortcut, true);
    window.addEventListener('keydown', blockCacheShortcut, true);
    window.addEventListener('keypress', blockCacheShortcut, true);
    window.addEventListener('keyup', blockCacheShortcut, true);
    </script>
    """,
    height=0, width=0
)

# 💓 [해결방법 1] 세션 만료 방지
components.html(
    """
    <script>
    setInterval(function() {
        fetch(window.parent.location.href, { method: 'HEAD', cache: 'no-store' });
        console.log("서버 세션 연장 핑(Ping) 전송 완료");
    }, 180000);
    </script>
    """,
    height=0, width=0
)

# 🔧 사진 파일에서 GPS 좌표(위도, 경도) 추출하는 함수 (최신/구버전 방식 둘 다 시도 + 실패 사유 반환)
def extract_gps_from_image(file_bytes):
    try:
        image = Image.open(io.BytesIO(file_bytes))

        gps_ifd = None

        # 방법 1: 최신 Pillow 권장 방식 (getexif + GPS 전용 IFD)
        try:
            exif = image.getexif()
            gps_ifd = exif.get_ifd(0x8825) or None
        except Exception:
            gps_ifd = None

        # 방법 2: 방법 1이 실패하면 구버전 호환 방식으로 재시도
        if not gps_ifd:
            try:
                legacy_exif = image._getexif()
                if legacy_exif:
                    for tag_id, value in legacy_exif.items():
                        if TAGS.get(tag_id, tag_id) == "GPSInfo":
                            gps_ifd = value
                            break
            except Exception:
                pass

        if not gps_ifd:
            return None, "이 사진에서 EXIF/GPS 데이터를 찾을 수 없습니다 (촬영 시 위치 서비스가 꺼져 있었거나, 전송 과정에서 메타데이터가 삭제됐을 수 있습니다)"

        gps_info = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}

        if "GPSLatitude" not in gps_info or "GPSLongitude" not in gps_info:
            return None, "GPS 태그는 있지만 위도/경도 값이 없습니다"

        def to_decimal(dms, ref):
            degrees, minutes, seconds = dms
            decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
            if ref in ["S", "W"]:
                decimal = -decimal
            return decimal

        lat = to_decimal(gps_info["GPSLatitude"], gps_info.get("GPSLatitudeRef", "N"))
        lng = to_decimal(gps_info["GPSLongitude"], gps_info.get("GPSLongitudeRef", "E"))
        return (lat, lng), "성공"
    except Exception as e:
        return None, f"이미지 처리 중 오류: {e}"


# 🔧 좌표를 카카오맵 링크로 만드는 함수 (표의 '📍 지도 보기' 클릭 시 카카오맵으로 열림)
def build_kakao_link(lat, lng, label="현장점검위치"):
    return f"https://map.kakao.com/link/map/{quote(label)},{lat},{lng}"


# 🔧 저장된 지도 링크(카카오맵/구글맵 형식) 또는 순수 좌표 텍스트에서 좌표만 다시 뽑아내는 함수
def extract_latlng_from_maps_url(url):
    if not url:
        return None
    text = str(url).strip()
    # 1) 카카오맵 링크 형식: /link/map/이름,위도,경도
    match = re.search(r"/link/map/[^,]*,([-\d.]+),([-\d.]+)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    # 2) (과거에 저장된) 구글맵 검색 링크 형식: query=위도,경도
    match = re.search(r"query=([-\d.]+)\s*,\s*([-\d.]+)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    # 3) 카카오맵/네이버지도 등에서 복사한 "위도, 경도" 순수 텍스트 형식
    match = re.match(r"^\s*(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def parse_timestamp(ts_str):
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(ts_str), fmt)
        except ValueError:
            pass
    return datetime.now()

# 1. Firebase 인증 및 초기화
if not firebase_admin._apps:
    try:
        key_dict = json.loads(st.secrets["textkey"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'sisul-2026.firebasestorage.app'
        })
    except Exception as e:
        st.error(f"보안키 인증 실패: Streamlit Secrets 설정을 확인하세요. ({e})")

db = firestore.client()
bucket = storage.bucket()

st.title("📱 대구공공시설관리공단 시설관리팀 운영 웹")
st.markdown("---")

# ☁️ 좌측 사이드바 용량 표시 및 사용자 로그아웃
with st.sidebar:
    st.success(f"✅ 접속자: {st.session_state.user_email}")
    if st.button("🚪 안전 로그아웃", use_container_width=True):
        st.session_state.google_auth = False
        st.session_state.pw_auth = False
        st.session_state.user_email = ""
        st.rerun()
    st.markdown("---")

    st.subheader("☁️ 클라우드 저장소 상태")
    try:
        blobs = bucket.list_blobs()
        total_bytes = sum(blob.size for blob in blobs if blob.size is not None)
        used_mb = round(total_bytes / (1024 * 1024), 1)
        total_mb = 5120.0
        left_mb = round(total_mb - used_mb, 1)
        usage_percent = min(used_mb / total_mb, 1.0)

        st.metric(label="사진 저장소 사용량", value=f"{used_mb} MB", delta=f"남은 무료 용량: {left_mb} MB (총 5GB)", delta_color="normal")
        st.progress(usage_percent, text=f"사용률: {usage_percent * 100:.3f}%")
        st.caption("※ 텍스트 데이터(Firestore)는 용량이 매우 적어 과금될 확률이 사실상 0%입니다.")
    except Exception as e:
        st.error(f"용량 정보를 불러올 수 없습니다. ({e})")

# 클라우드 DB에서 열 순서 불러오기
settings_ref = db.collection("system").document("settings")
settings_snap = settings_ref.get()

if not settings_snap.exists:
    initial_order = ["점검일", "사업처", "하천,지역", "시설물 종류", "시설명", "시설물 위치", "점검유형", "점검자", "점검내용", "점검결과", "현장 사진", "상태", "비고"]
    settings_ref.set({"column_order": initial_order})
    col_order = initial_order
else:
    col_order = settings_snap.to_dict().get("column_order", [])

# 2. Firebase 데이터 불러오기
@st.cache_data(ttl=3)
def load_infra_data():
    docs = db.collection("infra_management").stream()
    data_list = []

    for doc in docs:
        d = doc.to_dict()
        d["doc_id"] = doc.id

        for k, v in d.items():
            if isinstance(v, list):
                d[k] = v[0] if len(v) > 0 else None

        data_list.append(d)

    if not data_list:
        return pd.DataFrame([{"doc_id": "sample1", "점검일": "2026-02-25", "사업처": "서부", "하천,지역": "진천천", "시설물 종류": "스마트맨홀", "시설명": "진천 1번 맨홀", "시설물 위치": "", "점검유형": "일상점검", "점검자": "관리자", "점검내용": "스마트 맨홀 철거", "점검결과": "철거 완료", "현장 사진": "", "상태": "정상", "비고": "", "등록일시": "2026-01-01 00:00:00"}])

    df_temp = pd.DataFrame(data_list)
    if "등록일시" not in df_temp.columns:
        df_temp["등록일시"] = "2000-01-01 00:00:00"
    df_temp["등록일시"] = df_temp["등록일시"].fillna("2000-01-01 00:00:00")
    return df_temp.sort_values("등록일시", ascending=True).reset_index(drop=True)

df = load_infra_data()

# 중복 방지 청소
if "NO" in df.columns:
    df = df.drop(columns=["NO"])

# 열 순서 동기화
for c in col_order:
    if c not in df.columns:
        df[c] = ""

rogue_cols = [c for c in df.columns if c not in col_order and c not in ["doc_id", "등록일시", "NO"]]
if rogue_cols:
    col_order.extend(rogue_cols)
    settings_ref.update({"column_order": col_order})

df = df[["doc_id", "등록일시"] + col_order]

date_cols = [c for c in col_order if "일" in c or "날짜" in c]
for dc in date_cols:
    if dc in df.columns:
        df[dc] = pd.to_datetime(df[dc], errors="coerce").dt.date

# NO 세팅
df.insert(0, "NO", range(1, len(df) + 1))
display_order = ["NO"] + col_order

# 고급 설정 메뉴
with st.expander("⚙️ 고급 설정: 표 항목(열) 및 행(줄) 관리 기능", expanded=False):
    tab0, tab1, tab2, tab3 = st.tabs(["➕ 행(줄) 원하는 위치에 삽입", "➕ 항목(열) 삽입 및 추가", "📝 이름 일괄 변경", "↔️ 열 순서 영구 고정"])

    with tab0:
        st.caption("💡 선택한 기존 행의 **바로 윗 줄(위치)**에 새로운 빈 데이터 행을 강제로 끼워 넣습니다.")
        name_col_for_row = next((c for c in col_order if "명" in c or "이름" in c), col_order[0])
        row_position_options = ["맨 앞에 삽입", "맨 뒤에 추가"]

        for idx, row in df.iterrows():
            if not str(row["doc_id"]).startswith("sample"):
                no_val = row["NO"]
                name_val = row.get(name_col_for_row, "데이터")
                row_position_options.append(f"[NO. {no_val}] '{name_val}' 행 위에 삽입")

        with st.form("insert_row_form", clear_on_submit=True):
            selected_row_pos = st.selectbox("어느 위치에 행을 삽입할까요?", row_position_options)

            if st.form_submit_button("⚡ 지정 위치에 행 삽입 실행"):
                with st.spinner("지정된 위치에 빈 줄 끼워 넣는 중..."):
                    if selected_row_pos == "맨 앞에 삽입":
                        non_samples = df[~df["doc_id"].str.startswith("sample", na=False)]
                        if not non_samples.empty:
                            first_ts = parse_timestamp(non_samples.iloc[0]["등록일시"])
                            new_timestamp = (first_ts - timedelta(milliseconds=500)).strftime("%Y-%m-%d %H:%M:%S.%f")
                        else:
                            new_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                    elif selected_row_pos == "맨 뒤에 추가":
                        new_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                    else:
                        try:
                            target_no = int(selected_row_pos.split("]")[0].split(". ")[1])
                            target_idx = df[df["NO"] == target_no].index[0]

                            if target_idx == 0:
                                first_ts = parse_timestamp(df.iloc[0]["등록일시"])
                                new_timestamp = (first_ts - timedelta(milliseconds=500)).strftime("%Y-%m-%d %H:%M:%S.%f")
                            else:
                                t_current = parse_timestamp(df.iloc[target_idx]["등록일시"])
                                t_above = parse_timestamp(df.iloc[target_idx - 1]["등록일시"])
                                midpoint = t_above + (t_current - t_above) / 2
                                new_timestamp = midpoint.strftime("%Y-%m-%d %H:%M:%S.%f")
                        except Exception:
                            new_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

                    new_row_payload = {c: "" for c in col_order}
                    new_row_payload["등록일시"] = new_timestamp
                    for dc in date_cols:
                        new_row_payload[dc] = str(datetime.now().date())

                    db.collection("infra_management").add(new_row_payload)
                    st.success("🎉 지정된 위치에 새로운 행이 성공적으로 삽입되었습니다!")
                    st.session_state.table_version += 1
                    st.cache_data.clear()
                    st.rerun()

    with tab1:
        with st.form("add_column_form", clear_on_submit=True):
            new_col_name = st.text_input("새 항목 이름", placeholder="예: 관로 상태")
            position_options = ["맨 뒤에 추가", "맨 앞에 삽입"] + [f"'{c}' 열 앞에 삽입" for c in col_order]
            insert_pos = st.selectbox("삽입할 위치 지정", position_options)

            if st.form_submit_button("➕ 항목 삽입/추가") and new_col_name:
                new_col_name = new_col_name.strip()
                if new_col_name in df.columns or new_col_name == "NO":
                    st.warning("이미 표에 존재하는 항목 이름입니다.")
                elif new_col_name in ["doc_id", "등록일시"]:
                    st.error("시스템 예약어는 사용할 수 없습니다.")
                else:
                    with st.spinner("항목 삽입 중..."):
                        docs = db.collection("infra_management").stream()
                        for doc in docs: doc.reference.update({new_col_name: ""})

                        if insert_pos == "맨 뒤에 추가":
                            col_order.append(new_col_name)
                        elif insert_pos == "맨 앞에 삽입":
                            col_order.insert(0, new_col_name)
                        else:
                            target_col = insert_pos.split("'")[1]
                            target_idx = col_order.index(target_col)
                            col_order.insert(target_idx, new_col_name)

                        settings_ref.update({"column_order": col_order})
                        st.session_state.table_version += 1
                        st.cache_data.clear()
                        st.rerun()

    with tab2:
        with st.form("rename_column_form", clear_on_submit=True):
            st.caption("기존 항목의 이름을 서버 전체에서 안전하게 바꿉니다.")
            old_name = st.selectbox("변경할 기존 항목 선택", col_order)
            new_name = st.text_input("새로운 항목 이름", placeholder="예: 점검결과")
            if st.form_submit_button("✏️ 이름 변경 적용") and old_name and new_name:
                new_name = new_name.strip()
                if new_name in df.columns:
                    st.warning("이미 표에 존재하는 이름입니다.")
                elif new_name in ["doc_id", "등록일시", "NO"]:
                    st.error("시스템 예약어는 사용할 수 없습니다.")
                else:
                    with st.spinner("데이터 이전 및 이름 변경 중..."):
                        docs = db.collection("infra_management").stream()
                        for doc in docs:
                            d_dict = doc.to_dict()
                            if old_name in d_dict:
                                doc.reference.update({
                                    new_name: d_dict[old_name],
                                    old_name: firestore.DELETE_FIELD
                                })
                        idx = col_order.index(old_name)
                        col_order[idx] = new_name
                        settings_ref.update({"column_order": col_order})
                        st.success(f"'{old_name}' ➔ '{new_name}' 변경 완료!")
                        st.session_state.table_version += 1
                        st.cache_data.clear()
                        st.rerun()

    with tab3:
        st.caption("💡 아래 표에서 각 항목의 **[출력 순서]** 숫자를 원하는 대로 변경(더블클릭 후 입력)한 뒤, 맨 아래 **[💾 순서 영구 조정 적용]** 버튼을 누르면 메인 표에 즉시 반영됩니다.")
        order_data = pd.DataFrame({
            "항목(열) 이름": col_order,
            "출력 순서 (숫자가 작을수록 왼쪽 배치)": [i + 1 for i in range(len(col_order))]
        })

        edited_order_df = st.data_editor(
            order_data,
            column_config={
                "항목(열) 이름": st.column_config.TextColumn("항목(열) 이름", disabled=True),
                "출력 순서 (숫자가 작을수록 왼쪽 배치)": st.column_config.NumberColumn("출력 순서", min_value=1, max_value=len(col_order), step=1)
            },
            hide_index=True,
            use_container_width=True,
            key="column_reorder_matrix"
        )

        if st.button("💾 순서 영구 조정 적용", use_container_width=True, type="primary"):
            with st.spinner("클라우드 서버에 순서 고정 중..."):
                new_order = edited_order_df.sort_values("출력 순서 (숫자가 작을수록 왼쪽 배치)")["항목(열) 이름"].tolist()
                settings_ref.set({"column_order": new_order})
                st.success("🎉 열 순서 설정이 데이터베이스에 영구 반영되었습니다!")
                st.session_state.table_version += 1
                st.cache_data.clear()
                st.rerun()

st.markdown("---")

# 🛡️ 안전한 단건 입력 팝업 폼
with st.expander("➕ [안전 입력] 새로운 현장 점검 결과 단건 등록", expanded=False):
    st.info("💡 내용이 길거나 네트워크가 불안정할 때 사용하세요. 작성 중 튕겨도 서버 통신 오류를 막아주며, [전송]을 누르는 즉시 클라우드에 안전하게 저장됩니다.")
    with st.form("safe_single_entry_form", clear_on_submit=True):
        new_data = {}
        cols = st.columns(2)

        for i, c in enumerate(col_order):
            with cols[i % 2]:
                if "상태" in c:
                    new_data[c] = st.selectbox(c, ["정상", "점검필요", "정비중", "조치완료"])
                elif "일" in c or "날짜" in c:
                    new_data[c] = st.date_input(c, datetime.now().date())
                elif "내용" in c or "결과" in c or "비고" in c:
                    new_data[c] = st.text_area(c, placeholder=f"{c} 입력")
                elif "사진" in c or "URL" in c or "링크" in c:
                    st.caption(f"※ '{c}' 항목은 전송 완료 후 하단의 '사진 등록' 메뉴를 통해 업로드하세요.")
                    new_data[c] = ""
                else:
                    new_data[c] = st.text_input(c, placeholder=f"{c} 입력")

        if st.form_submit_button("🚀 클라우드로 즉시 전송하기", type="primary", use_container_width=True):
            with st.spinner("안전하게 데이터 전송 중..."):
                for k, v in new_data.items():
                    if isinstance(v, type(datetime.now().date())):
                        new_data[k] = str(v)

                new_data["등록일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                db.collection("infra_management").add(new_data)

                st.session_state.table_version += 1
                st.cache_data.clear()
                st.success("🎉 데이터가 증발 없이 안전하게 서버에 전송되었습니다!")
                st.rerun()

st.markdown("---")

col_title, col_save = st.columns([7, 3])
with col_title:
    st.subheader("📊 하수관로 시설물 점검이력대장 (엑셀 형태)")
    st.caption("💡 **Tip:** 표 우측 상단의 확대(⛶)로 넓게 작업하신 후, **축소(ESC)해서 우측 [일괄 저장]**을 누르세요. 창을 줄여도 작성한 내용은 유지됩니다!")
with col_save:
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    save_btn = st.button("💾 표 변경사항 일괄 저장", use_container_width=True, type="primary")

for c in col_order:
    if any(keyword in c for keyword in ["사진", "URL", "링크", "위치", "지도"]):
        df[c] = df[c].map(lambda x: None if pd.isna(x) or str(x).strip() == "" else x)

dynamic_config = {
    "doc_id": None,
    "등록일시": None,
    "NO": st.column_config.NumberColumn("NO", disabled=True)
}

for c in col_order:
    if "상태" in c:
        dynamic_config[c] = st.column_config.SelectboxColumn(c, options=["정상", "점검필요", "정비중", "조치완료"])
    elif any(keyword in c for keyword in ["사진", "URL", "링크"]):
        dynamic_config[c] = st.column_config.ImageColumn(c, help="📸 현장 점검 사진 미리보기")
    elif "위치" in c or "지도" in c:
        dynamic_config[c] = st.column_config.LinkColumn(c, display_text="📍 지도 보기")
    elif "일" in c or "날짜" in c:
        dynamic_config[c] = st.column_config.DateColumn(c, default=datetime.now().date())
    elif "내용" in c:
        dynamic_config[c] = st.column_config.TextColumn(c, width="medium")
    elif any(keyword in c for keyword in ["비고", "결과"]):
        dynamic_config[c] = st.column_config.TextColumn(c, width="large")

editor_key = f"infra_table_editor_{st.session_state.table_version}"

edited_df = st.data_editor(
    df,
    column_order=display_order,
    column_config=dynamic_config,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key=editor_key
)

st.markdown(" ")
export_df = edited_df[display_order].copy()

col_down1, col_down2 = st.columns(2)

with col_down1:
    csv_data = export_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 기본 표 다운로드 (빠름, 텍스트 전용)",
        data=csv_data,
        file_name=f"하수관로_시설물_점검이력대장_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
        type="secondary"
    )

with col_down2:
    if st.button("🖼️ 사진 포함 정식 엑셀 생성하기", use_container_width=True):
        photo_col_name = next((c for c in col_order if "사진" in c or "URL" in c or "링크" in c), None)

        with st.spinner("클라우드에서 현장 사진들을 모두 불러와 엑셀 셀 크기에 딱 맞게 자동 조정 중입니다..."):

            # 🔧 [개선] 표에는 대표사진 1장만 남아있으므로, DB에서 각 행의 '전체 사진 목록'을 doc_id 기준으로 다시 불러온다
            raw_docs = db.collection("infra_management").stream()
            full_photos_by_id = {}
            for doc in raw_docs:
                d = doc.to_dict()
                raw_val = d.get(photo_col_name, []) if photo_col_name else []
                if isinstance(raw_val, list):
                    urls = [str(u).strip() for u in raw_val if str(u).strip().startswith("http")]
                elif isinstance(raw_val, str) and raw_val.strip().startswith("http"):
                    urls = [raw_val.strip()]
                else:
                    urls = []
                full_photos_by_id[doc.id] = urls

            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            worksheet = workbook.add_worksheet("점검이력대장")

            header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            cell_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})

            headers = display_order
            for col_num, header in enumerate(headers):
                worksheet.write(0, col_num, header, header_format)
                worksheet.set_column(col_num, col_num, 15)

            # 🔧 [개선] 사진을 세로로 쌓는 방식 — 행마다 사진 개수에 맞춰 높이를 다르게 자동 조정
            single_photo_row_height = 90       # 사진 한 장당 차지할 행 높이
            col_width_excel = 35               # 사진 열 너비(고정)
            target_px_width = col_width_excel * 7
            target_px_height_per_img = single_photo_row_height * 1.3

            photo_col_idx = headers.index(photo_col_name) if photo_col_name in headers else -1
            if photo_col_idx != -1:
                worksheet.set_column(photo_col_idx, photo_col_idx, col_width_excel)

            MAX_PHOTOS_PER_ROW = 10  # 지나치게 큰 행 방지용 안전장치

            for row_num, (_, row) in enumerate(edited_df.iterrows()):
                doc_id_val = str(row.get("doc_id", ""))
                cell_data = row.get(photo_col_name, "") if photo_col_idx != -1 else None

                photo_urls = full_photos_by_id.get(doc_id_val, [])
                if not photo_urls and cell_data:
                    # DB에서 못 찾은 경우(예: 저장 전 sample 행)엔 표에 있던 대표사진이라도 사용
                    single = cell_data[0] if isinstance(cell_data, list) else cell_data
                    if isinstance(single, str) and single.startswith("http"):
                        photo_urls = [single]
                photo_urls = photo_urls[:MAX_PHOTOS_PER_ROW]

                # 사진 개수에 맞춰 이 행의 높이를 동적으로 늘림 (최소 1장 높이는 확보)
                photo_count = max(len(photo_urls), 1)
                row_height = single_photo_row_height * photo_count
                worksheet.set_row(row_num + 1, row_height)

                for col_num, col_name in enumerate(display_order):
                    val_data = row.get(col_name, "")

                    if col_num == photo_col_idx:
                        if photo_urls:
                            for i, url in enumerate(photo_urls):
                                try:
                                    img_res = requests.get(url, timeout=5)
                                    img_data = io.BytesIO(img_res.content)
                                    image = Image.open(img_data)
                                    orig_width, orig_height = image.size

                                    scale_x = (target_px_width - 10) / orig_width
                                    scale_y = (target_px_height_per_img - 10) / orig_height
                                    optimal_scale = min(scale_x, scale_y)

                                    worksheet.insert_image(
                                        row_num + 1, col_num, url,
                                        {
                                            'image_data': img_data,
                                            'x_scale': optimal_scale,
                                            'y_scale': optimal_scale,
                                            'x_offset': 5,
                                            'y_offset': 5 + i * target_px_height_per_img,
                                            'object_position': 1
                                        }
                                    )
                                except Exception:
                                    worksheet.write(row_num + 1, col_num, "사진 로드 실패", cell_format)
                        else:
                            worksheet.write(row_num + 1, col_num, "", cell_format)
                    else:
                        val = str(val_data) if val_data is not None else ""
                        worksheet.write(row_num + 1, col_num, val, cell_format)

            workbook.close()
            st.session_state.excel_output = output.getvalue()

        st.success("✅ 엑셀 파일 생성이 완료되었습니다! 아래 버튼을 눌러 저장하세요.")

    if "excel_output" in st.session_state:
        st.download_button(
            label="💾 완성된 엑셀(.xlsx) 저장하기",
            data=st.session_state.excel_output,
            file_name=f"하수관로_시설물_점검이력대장_사진포함_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary"
        )

# 4. 수동 일괄 저장 로직
photo_col = next((c for c in col_order if "사진" in c or "URL" in c or "링크" in c), None)

if save_btn:
    editor_state = st.session_state.get(editor_key, {})
    has_changes = False

    if editor_state.get("edited_rows"):
        for row_idx, changes in editor_state["edited_rows"].items():
            doc_id = df.iloc[int(row_idx)]["doc_id"]
            if "NO" in changes: del changes["NO"]

            if photo_col and photo_col in changes and (changes[photo_col] is None or str(changes[photo_col]).strip() == ""):
                changes[photo_col] = []

            for k, v in list(changes.items()):
                if isinstance(v, type(datetime.now().date())):
                    changes[k] = str(v)

                if ("위치" in k or "지도" in k) and v:
                    val_str = str(v).strip()
                    if not (val_str.startswith("http://") or val_str.startswith("https://")):
                        coord_match = re.match(r"^\s*(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$", val_str)
                        if coord_match:
                            changes[k] = build_kakao_link(float(coord_match.group(1)), float(coord_match.group(2)))
                        else:
                            changes[k] = f"https://map.kakao.com/?q={quote(val_str)}"

            if str(doc_id).startswith("sample"):
                row_full = df.iloc[int(row_idx)].to_dict()
                row_full.update(changes)
                if "doc_id" in row_full: del row_full["doc_id"]
                if "NO" in row_full: del row_full["NO"]
                row_full["등록일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                for dc in date_cols:
                    if dc in row_full: row_full[dc] = str(row_full.get(dc, datetime.now().date()))
                row_full = {k: ("" if pd.isna(v) else v) for k, v in row_full.items()}
                db.collection("infra_management").add(row_full)
            else:
                db.collection("infra_management").document(str(doc_id)).update(changes)
        has_changes = True

    if editor_state.get("added_rows"):
        for row in editor_state["added_rows"]:
            row_data = row.copy()
            if "NO" in row_data: del row_data["NO"]

            row_data["등록일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            for dc in date_cols:
                if dc in row_data: row_data[dc] = str(row_data.get(dc, datetime.now().date()))

            for k, v in list(row_data.items()):
                if ("위치" in k or "지도" in k) and v:
                    val_str = str(v).strip()
                    if not (val_str.startswith("http://") or val_str.startswith("https://")):
                        coord_match = re.match(r"^\s*(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$", val_str)
                        if coord_match:
                            row_data[k] = build_kakao_link(float(coord_match.group(1)), float(coord_match.group(2)))
                        else:
                            row_data[k] = f"https://map.kakao.com/?q={quote(val_str)}"

            row_data = {k: ("" if pd.isna(v) else v) for k, v in row_data.items()}
            db.collection("infra_management").add(row_data)
        has_changes = True

    if editor_state.get("deleted_rows"):
        for row_idx in editor_state["deleted_rows"]:
            doc_id = df.iloc[int(row_idx)]["doc_id"]
            if not str(doc_id).startswith("sample"):
                try:
                    doc_ref = db.collection("infra_management").document(str(doc_id))
                    doc_snap = doc_ref.get()
                    if doc_snap.exists:
                        doc_data = doc_snap.to_dict()
                        if photo_col:
                            photo_url = doc_data.get(photo_col, "")
                            if isinstance(photo_url, list):
                                for url in photo_url:
                                    if "sisul-2026.firebasestorage.app/" in url:
                                        blob_name = url.split("sisul-2026.firebasestorage.app/")[-1]
                                        try: bucket.blob(blob_name).delete()
                                        except Exception: pass
                            elif photo_url and "sisul-2026.firebasestorage.app/" in photo_url:
                                blob_name = photo_url.split("sisul-2026.firebasestorage.app/")[-1]
                                try: bucket.blob(blob_name).delete()
                                except Exception: pass
                    doc_ref.delete()
                except Exception:
                    pass
        has_changes = True

    if has_changes:
        st.cache_data.clear()
        st.success("🎉 작성하신 모든 내용이 클라우드에 안전하게 일괄 저장되었습니다!")
        st.rerun()
    else:
        st.info("새로 변경되거나 추가된 내용이 없습니다.")

st.markdown("---")

# 5. 모바일 현장 사진 업로드 (💡 에러 및 잔상 완벽 해결 버전)
st.subheader("📸 모바일 현장 점검 사진 등록")

# 🔧 직전 업로드의 GPS 자동인식 결과를 rerun 이후에도 보여줌
if "gps_upload_result" in st.session_state:
    result = st.session_state.pop("gps_upload_result")
    count = result["count"]
    status = result["status"]
    reasons = result["reasons"]

    if status == "applied":
        st.success(f"🎉 {count}장의 사진이 추가되었고, 사진 속 GPS 좌표로 위치도 자동 등록되었습니다!")
    elif status == "already_filled":
        st.success(f"🎉 {count}장의 사진이 추가되었습니다. (위치 칸에 이미 값이 있어 GPS로 덮어쓰지 않았습니다)")
    elif status == "no_gps":
        st.success(f"🎉 {count}장의 사진이 추가되었습니다.")
        with st.expander("ℹ️ 위치 칸이 자동으로 안 채워진 이유", expanded=True):
            for i, reason in enumerate(reasons):
                st.write(f"- 사진 {i+1}: {reason}")
    else:
        st.success(f"🎉 성공적으로 {count}장의 사진이 대장에 추가 통합되었습니다!")

if photo_col:
    date_col = next((c for c in col_order if "일" in c or "날짜" in c), None)

    name_candidates = [c for c in col_order if "명" in c or "이름" in c]
    if name_candidates:
        name_col = name_candidates[0]
    else:
        other_cols = [c for c in col_order if c != date_col]
        name_col = other_cols[0] if other_cols else col_order[0]

    facility_options = {}

    for idx, row in edited_df.iloc[::-1].iterrows():
        if pd.isna(row['doc_id']) or str(row['doc_id']) == "nan":
            continue

        no_val = row.get("NO", "?")
        name_val = row.get(name_col, "이름없음")
        date_val = row.get(date_col, "날짜미상") if date_col else ""

        label = f"[NO. {no_val}] {name_val} (점검일: {date_val})"
        facility_options[label] = str(row['doc_id'])

    if facility_options:
        selected_label = st.selectbox("사진을 매핑할 시설물을 선택하세요:", list(facility_options.keys()))
        target_doc_id = facility_options[selected_label]

        target_doc_ref = db.collection("infra_management").document(target_doc_id)
        doc_snap = target_doc_ref.get()

        # 💡 방어 로직: DB에 비정상적인 빈칸 데이터가 섞여 있어도 걸러내어 안전하게 사진만 표시합니다.
        existing_photos = []
        if doc_snap.exists:
            raw_data = doc_snap.to_dict().get(photo_col, [])
            if isinstance(raw_data, list):
                existing_photos = [str(url).strip() for url in raw_data if str(url).strip().startswith("http")]
            elif isinstance(raw_data, str) and raw_data.strip().startswith("http"):
                existing_photos = [raw_data.strip()]

        # 기존 사진 출력 및 삭제 구역
        if existing_photos:
            st.write(f"📊 현재 이 항목에 등록된 누적 사진: 총 {len(existing_photos)}장 (첫 번째 사진이 표에 대표로 표시됩니다)")
            img_cols = st.columns(min(len(existing_photos), 5))
            for i, img_url in enumerate(existing_photos):
                with img_cols[i % 5]:
                    st.image(img_url, caption=f"사진 #{i+1}", use_container_width=True)

            if st.button("🗑️ 이 항목의 기존 사진 모두 삭제(초기화)", type="secondary"):
                with st.spinner("사진 링크 제거 중..."):
                    target_doc_ref.update({photo_col: []})
                    st.success("기존 사진 데이터가 완전히 초기화되었습니다.")
                    st.cache_data.clear()
                    st.rerun()

        st.markdown(" ")

        # 💡 해결 방법: Streamlit 폼(Form)을 사용해 '사진 업로드'와 '찌꺼기 자동 초기화'를 가장 안전하게 수행합니다.
        with st.form(key=f"upload_form_{target_doc_id}", clear_on_submit=True):
            uploaded_files = st.file_uploader(
                "스마트폰 카메라로 촬영하거나 갤러리에서 사진들을 선택하세요. (여러 장 동시 선택 가능)",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=True
            )
            overwrite_gps = st.checkbox("📍 위치 칸에 이미 값이 있어도 새 사진의 GPS 좌표로 덮어쓰기", value=False)
            submit_upload = st.form_submit_button("🚀 선택한 모든 사진 추가 등록", type="primary", use_container_width=True)

            if submit_upload:
                if uploaded_files:
                    with st.spinner("모든 이미지 서버 전송 중..."):
                        try:
                            new_urls = []
                            detected_latlng = None  # 🔧 여러 장 중 GPS 있는 첫 사진 좌표를 저장
                            gps_reasons = []  # 🔧 진단용: 각 사진의 GPS 추출 결과 사유

                            for idx, uploaded_file in enumerate(uploaded_files):
                                file_bytes = uploaded_file.read()  # 🔧 바이트를 한 번만 읽어서 재사용

                                gps_result, gps_reason = extract_gps_from_image(file_bytes)
                                gps_reasons.append(gps_reason)
                                if detected_latlng is None and gps_result:
                                    detected_latlng = gps_result

                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                file_name = f"infra_photos/{target_doc_id}_{timestamp}_{idx}.png"

                                blob = bucket.blob(file_name)
                                blob.upload_from_string(file_bytes, content_type="image/png")
                                blob.make_public()
                                new_urls.append(blob.public_url)

                            if target_doc_id.startswith("sample"):
                                st.warning("먼저 표에 내용을 입력하시고 [일괄 저장]을 누르신 후에 사진을 올려주세요.")
                            else:
                                updated_photos = existing_photos + new_urls
                                update_payload = {photo_col: updated_photos}

                                # 🔧 GPS 좌표를 찾았고, 위치 칸이 비어있거나 덮어쓰기를 선택했으면 자동으로 채움
                                location_col = next((c for c in col_order if "위치" in c or "지도" in c), None)
                                location_status = "no_gps"  # no_gps / already_filled / applied / no_column
                                if not location_col:
                                    location_status = "no_column"
                                elif detected_latlng:
                                    current_loc = doc_snap.to_dict().get(location_col, "") if doc_snap.exists else ""
                                    if str(current_loc).strip() and not overwrite_gps:
                                        location_status = "already_filled"
                                    else:
                                        lat, lng = detected_latlng
                                        update_payload[location_col] = build_kakao_link(lat, lng)
                                        location_status = "applied"

                                target_doc_ref.update(update_payload)

                                # 🔧 rerun 직전 메시지가 바로 사라지는 문제 방지: session_state에 저장해뒀다가 재실행 후 표시
                                st.session_state["gps_upload_result"] = {
                                    "count": len(new_urls),
                                    "status": location_status,
                                    "reasons": gps_reasons,
                                }
                                st.cache_data.clear()
                                st.rerun()
                        except Exception as e:
                            st.error(f"사진 매핑 실패: {e}")
                else:
                    st.warning("선택된 사진 파일이 없습니다. 먼저 사진을 골라주세요.")
    else:
        st.info("등록 가능한 시설물이 없습니다. 위의 표에 데이터를 먼저 입력해주세요.")
else:
    st.warning("이름에 '사진', 'URL', '링크' 중 하나가 포함된 항목(열)이 있어야 사진을 매핑할 수 있습니다.")

st.markdown("---")
st.subheader("🗺️ 시설물 위치 지도 확인")

location_col_for_map = next((c for c in col_order if "위치" in c or "지도" in c), None)
KAKAO_JS_KEY = st.secrets.get("KAKAO_JS_KEY", "")

if location_col_for_map and photo_col and 'facility_options' in dir() and facility_options:
    map_facility_label = st.selectbox(
        "지도를 확인할 시설물을 선택하세요:",
        list(facility_options.keys()),
        key="map_facility_select"
    )
    map_doc_id = facility_options[map_facility_label]
    map_doc_ref = db.collection("infra_management").document(map_doc_id)
    map_doc_snap = map_doc_ref.get()

    if map_doc_snap.exists:
        saved_url = map_doc_snap.to_dict().get(location_col_for_map, "")
        latlng = extract_latlng_from_maps_url(saved_url)

        if latlng and KAKAO_JS_KEY:
            lat, lng = latlng
            zoom_level = st.slider("확대 수준 (숫자가 작을수록 확대됨)", min_value=1, max_value=10, value=3, key="map_zoom")
            kakao_map_html = f"""
            <div id="kakaoMap" style="width:100%;height:450px;"></div>
            <script src="//dapi.kakao.com/v2/maps/sdk.js?appkey={KAKAO_JS_KEY}"></script>
            <script>
                var container = document.getElementById('kakaoMap');
                var options = {{
                    center: new kakao.maps.LatLng({lat}, {lng}),
                    level: {zoom_level}
                }};
                var map = new kakao.maps.Map(container, options);
                var markerPosition = new kakao.maps.LatLng({lat}, {lng});
                var marker = new kakao.maps.Marker({{ position: markerPosition }});
                marker.setMap(map);
            </script>
            """
            components.html(kakao_map_html, height=470)
            st.caption(f"📍 좌표: {lat:.6f}, {lng:.6f}")
        elif latlng and not KAKAO_JS_KEY:
            st.warning("⚠️ 좌표는 있지만, Streamlit Secrets에 KAKAO_JS_KEY가 등록되지 않아 지도를 표시할 수 없습니다.")
            st.caption(f"📍 좌표: {latlng[0]:.6f}, {latlng[1]:.6f}")
        else:
            st.info("이 시설물은 아직 좌표(위치)가 등록되지 않았습니다.")

        st.markdown(" ")
        with st.expander("✏️ 좌표 직접 입력 / 수정 (카카오맵·네이버지도에서 복사해오기)", expanded=(latlng is None)):
            st.caption(
                "💡 카카오맵 앱이나 네이버지도 앱에서 해당 위치를 길게 눌러 '좌표 복사'를 누르면 "
                "\"위도, 경도\" 형식의 텍스트가 복사됩니다. 그걸 그대로 아래에 붙여넣으세요."
            )
            st.link_button("🗺️ 카카오맵에서 위치 검색하기 (새 탭)", "https://map.kakao.com/")

            pasted_coord = st.text_input(
                "좌표 붙여넣기 (예: 35.857350, 128.601470)",
                key=f"paste_coord_{map_doc_id}"
            )
            if st.button("💾 이 좌표로 저장", key=f"save_coord_{map_doc_id}"):
                parsed = extract_latlng_from_maps_url(pasted_coord)
                if parsed:
                    p_lat, p_lng = parsed
                    map_doc_ref.update({
                        location_col_for_map: build_kakao_link(p_lat, p_lng)
                    })
                    st.success("🎉 좌표가 저장되었습니다!")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("좌표 형식을 인식하지 못했습니다. \"위도, 경도\" 형식인지 확인해주세요.")
elif location_col_for_map:
    st.info("등록된 시설물이 없습니다. 위의 표에 데이터를 먼저 입력해주세요.")
else:
    st.warning("이름에 '위치' 또는 '지도'가 포함된 항목(열)이 있어야 지도를 표시할 수 있습니다.")
