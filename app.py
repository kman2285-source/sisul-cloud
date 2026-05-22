import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore, storage
import json
from datetime import datetime

# 페이지 기본 설정 (모바일 최적화 레이아웃)
st.set_page_config(page_title="스마트 인프라 관리 시스템", layout="wide")

# 1. Firebase 마스터키 인증 및 초기화
if not firebase_admin._apps:
    try:
        # Streamlit Cloud의 Secrets에 등록할 'textkey' 보안 주입
        key_dict = json.loads(st.secrets["textkey"])
        cred = credentials.Certificate(key_dict)
        
        # Firebase 초기화 (본인의 스토리지 버킷 주소 입력)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'sisul-2026.appspot.com'
        })
    except Exception as e:
        st.error(f"보안키 인증 실패: Streamlit Secrets 설정을 확인하세요. ({e})")

db = firestore.client()
bucket = storage.bucket()

st.title("📱 스마트 인프라 통합 관리 웹")
st.markdown("---")

# 2. Firebase Firestore에서 실시간 데이터 불러오기 함수
@st.cache_data(ttl=5)  # 5초 간격으로 데이터 캐시 갱신
def load_infra_data():
    docs = db.collection("infra_management").stream()
    data_list = []
    for doc in docs:
        d = doc.to_dict()
        d["doc_id"] = doc.id  # Firestore 문서 고유 ID 기록
        data_list.append(d)
    
    if not data_list:
        # 최초 실행 시 데이터베이스가 비어있을 경우 보여줄 초기 샘플 데이터
        initial_data = [
            {"doc_id": "sample1", "시설물명": "신천대로 교량 A지점", "상태": "정상", "점검자": "관리자", "사진URL": "", "최종점검일": "2026-05-22"},
            {"doc_id": "sample2", "시설물명": "범어 지하차도 배수펌프", "상태": "점검필요", "점검자": "관리자", "사진URL": "", "최종점검일": "2026-05-22"}
        ]
        return pd.DataFrame(initial_data)
    
    return pd.DataFrame(data_list)

# 💡 [에러 해결 부분] 데이터 로드 및 날짜 데이터 타입 강제 변환
try:
    df = load_infra_data()
    # '최종점검일' 열이 존재하면, 일반 텍스트를 달력 UI가 인식할 수 있는 날짜(Date) 형식으로 변환합니다.
    if "최종점검일" in df.columns:
        df["최종점검일"] = pd.to_datetime(df["최종점검일"], errors="coerce").dt.date
except Exception as e:
    df = pd.DataFrame(columns=["doc_id", "시설물명", "상태", "점검자", "사진URL", "최종점검일"])
    df["최종점검일"] = pd.to_datetime(df["최종점검일"]).dt.date

st.subheader("📊 인프라 자산 관리 그리드 (엑셀 형태)")
st.caption("💡 셀을 더블클릭하여 내용을 직접 수정하거나, 맨 아래 행에서 새로운 시설물을 추가할 수 있습니다.")

# 3. 엑셀 형태의 인터랙티브 데이터 에디터 UI (st.data_editor)
edited_df = st.data_editor(
    df,
    column_config={
        "doc_id": None,  # 시스템용 ID는 화면에서 숨김
        "상태": st.column_config.SelectboxColumn(
            "상태",
            options=["정상", "점검필요", "정비중", "조치완료"],
            required=True
        ),
        "사진URL": st.column_config.LinkColumn("현장사진 링크", display_text="📸 사진 보기"),
        "최종점검일": st.column_config.DateColumn("최종점검일", default=datetime.now().date())
    },
    num_rows="dynamic",  # 사용자가 자유롭게 행을 추가/삭제 가능하게 설정
    use_container_width=True,
    key="infra_table_editor"
)

# 4. 엑셀 수정 내용 데이터베이스(Firestore) 영구 저장 로직
col1, col2 = st.columns([1, 5])
with col1:
    if st.button("💾 변경사항 저장", type="primary"):
        with st.spinner("클라우드 데이터베이스 동기화 중..."):
            try:
                # 데이터프레임 내 모든 행을 순회하며 Firestore에 반영
                for index, row in edited_df.iterrows():
                    # DB에 넣을 때는 다시 텍스트(문자열)로 변환해서 안전하게 저장
                    inspect_date = str(row["최종점검일"]) if pd.notna(row["최종점검일"]) else datetime.now().strftime("%Y-%m-%d")
                    
                    row_data = {
                        "시설물명": row["시설물명"] if pd.notna(row["시설물명"]) else "이름 없음",
                        "상태": row["상태"] if pd.notna(row["상태"]) else "정상",
                        "점검자": row["점검자"] if pd.notna(row["점검자"]) else "미지정",
                        "사진URL": row["사진URL"] if pd.notna(row["사진URL"]) else "",
                        "최종점검일": inspect_date
                    }
                    
                    # 신규 행 추가이거나 샘플 데이터인 경우 새로 생성
                    if pd.isna(row["doc_id"]) or str(row["doc_id"]).startswith("sample") or row["doc_id"] == "":
                        db.collection("infra_management").add(row_data)
                    else:
                        # 기존에 존재하던 행은 덮어쓰기 수정
                        db.collection("infra_management").document(str(row["doc_id"])).set(row_data)
                
                st.success("데이터베이스에 영구 저장되었습니다!")
                st.cache_data.clear()  # 캐시를 비워 화면 강제 갱신
                st.rerun()
            except Exception as e:
                st.error(f"데이터 저장 중 오류 발생: {e}")

st.markdown("---")

# 5. 모바일 현장 사진 촬영 및 클라우드 업로드 섹션
st.subheader("📸 모바일 현장 점검 사진 등록")

# 등록된 시설물 목록을 선택박스로 제공
facility_list = edited_df["시설물명"].dropna().unique()
if len(facility_list) > 0:
    target_facility = st.selectbox("사진을 매핑할 시설물을 선택하세요:", facility_list)
    
    # 모바일 카메라 및 파일 업로드 활성화
    uploaded_file = st.file_uploader("스마트폰 카메라로 촬영하거나 갤러리에서 사진을 선택하세요.", type=["jpg", "jpeg", "png"])
    
    if uploaded_file is not None:
        if st.button("🚀 선택한 시설물에 사진 등록", type="secondary"):
            with st.spinner("구글 스토리지 서버로 고화질 이미지 전송 중..."):
                try:
                    # 파일명 중복 방지를 위한 고유 파일 경로 생성
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_name = f"infra_photos/{target_facility}_{timestamp}.png"
                    
                    # Firebase Storage에 파일 바이너리 업로드
                    blob = bucket.blob(file_name)
                    blob.upload_from_string(uploaded_file.read(), content_type="image/png")
                    
                    # 업로드된 파일에 접근 가능한 퍼블릭 URL 권한 부여
                    blob.make_public()
                    public_url = blob.public_url
                    
                    # Firestore DB에서 해당 시설물명을 가진 문서의 사진URL 필드 즉시 업데이트
                    query = db.collection("infra_management").where("시설물명", "==", target_facility).stream()
                    matched = False
                    for doc in query:
                        db.collection("infra_management").document(doc.id).update({"사진URL": public_url})
                        matched = True
                    
                    if matched:
                        st.success(f"🎉 {target_facility}에 사진이 성공적으로 등록되었습니다!")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.warning("선택하신 시설물이 먼저 '변경사항 저장'을 통해 DB에 등록되어 있어야 사진 매핑이 가능합니다.")
                        
                except Exception as e:
                    st.error(f"사진 업로드 실패: {e}")
else:
    st.info("엑셀 그리드에 시설물을 먼저 입력하고 저장해 주세요.")
