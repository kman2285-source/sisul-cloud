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
        key_dict = json.loads(st.secrets["textkey"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'sisul-2026.firebasestorage.app'
        })
    except Exception as e:
        st.error(f"보안키 인증 실패: Streamlit Secrets 설정을 확인하세요. ({e})")

db = firestore.client()
bucket = storage.bucket()

st.title("📱 스마트 인프라 통합 관리 웹")
st.markdown("---")

# ☁️ 좌측 사이드바 클라우드 저장소 실시간 용량 표시
with st.sidebar:
    st.subheader("☁️ 클라우드 저장소 상태")
    try:
        blobs = bucket.list_blobs()
        total_bytes = sum(blob.size for blob in blobs if blob.size is not None)
        
        used_mb = round(total_bytes / (1024 * 1024), 1)
        total_mb = 5120.0  
        left_mb = round(total_mb - used_mb, 1)
        
        usage_percent = used_mb / total_mb
        if usage_percent > 1.0:
            usage_percent = 1.0
            
        st.metric(
            label="사진 저장소 사용량", 
            value=f"{used_mb} MB", 
            delta=f"남은 무료 용량: {left_mb} MB (총 5GB)", 
            delta_color="normal"
        )
        st.progress(usage_percent, text=f"사용률: {usage_percent * 100:.3f}%")
        st.caption("※ 텍스트 데이터(Firestore)는 용량이 매우 적어 과금될 확률이 사실상 0%입니다.")
    except Exception as e:
        st.error(f"용량 정보를 불러올 수 없습니다. ({e})")

# 2. Firebase Firestore에서 실시간 데이터 불러오기 함수
@st.cache_data(ttl=5)
def load_infra_data():
    docs = db.collection("infra_management").stream()
    data_list = []
    for doc in docs:
        d = doc.to_dict()
        d["doc_id"] = doc.id
        data_list.append(d)
    
    if not data_list:
        initial_data = [
            {"doc_id": "sample1", "시설물명": "신천대로 교량 A지점", "상태": "정상", "점검자": "관리자", "사진URL": "", "최종점검일": "2026-05-22"},
            {"doc_id": "sample2", "시설물명": "범어 지하차도 배수펌프", "상태": "점검필요", "점검자": "관리자", "사진URL": "", "최종점검일": "2026-05-22"}
        ]
        return pd.DataFrame(initial_data)
    
    return pd.DataFrame(data_list)

try:
    df = load_infra_data()
    if "최종점검일" in df.columns:
        df["최종점검일"] = pd.to_datetime(df["최종점검일"], errors="coerce").dt.date
except Exception as e:
    df = pd.DataFrame(columns=["doc_id", "시설물명", "상태", "점검자", "사진URL", "최종점검일"])
    df["최종점검일"] = pd.to_datetime(df["최종점검일"]).dt.date

st.subheader("📊 인프라 자산 관리 그리드 (엑셀 형태)")
st.caption("💡 셀을 더블클릭하여 내용을 직접 수정하거나, 맨 아래 행에서 새로운 시설물을 추가할 수 있습니다.")

# 3. 엑셀 형태의 인터랙티브 데이터 에디터 UI
edited_df = st.data_editor(
    df,
    column_config={
        "doc_id": None,
        "상태": st.column_config.SelectboxColumn("상태", options=["정상", "점검필요", "정비중", "조치완료"], required=True),
        "사진URL": st.column_config.LinkColumn("현장사진 링크", display_text="📸 사진 보기"),
        "최종점검일": st.column_config.DateColumn("최종점검일", default=datetime.now().date())
    },
    num_rows="dynamic",
    use_container_width=True,
    key="infra_table_editor"
)

# 4. 엑셀 수정 내용 데이터베이스 영구 저장 로직
col1, col2 = st.columns([1, 5])
with col1:
    if st.button("💾 변경사항 저장", type="primary"):
        with st.spinner("클라우드 데이터베이스 동기화 중..."):
            try:
                for index, row in edited_df.iterrows():
                    inspect_date = str(row["최종점검일"]) if pd.notna(row["최종점검일"]) else datetime.now().strftime("%Y-%m-%d")
                    row_data = {
                        "시설물명": row["시설물명"] if pd.notna(row["시설물명"]) else "이름 없음",
                        "상태": row["상태"] if pd.notna(row["상태"]) else "정상",
                        "점검자": row["점검자"] if pd.notna(row["점검자"]) else "미지정",
                        "사진URL": row["사진URL"] if pd.notna(row["사진URL"]) else "",
                        "최종점검일": inspect_date
                    }
                    
                    if pd.isna(row["doc_id"]) or str(row["doc_id"]).startswith("sample") or row["doc_id"] == "":
                        db.collection("infra_management").add(row_data)
                    else:
                        db.collection("infra_management").document(str(row["doc_id"])).set(row_data)
                
                st.success("데이터베이스에 영구 저장되었습니다!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"데이터 저장 중 오류 발생: {e}")

st.markdown("---")

# 5. 모바일 현장 사진 촬영 및 클라우드 업로드 섹션
st.subheader("📸 모바일 현장 점검 사진 등록")

facility_list = edited_df["시설물명"].dropna().unique()
if len(facility_list) > 0:
    target_facility = st.selectbox("사진을 매핑할 시설물을 선택하세요:", facility_list)
    uploaded_file = st.file_uploader("스마트폰 카메라로 촬영하거나 갤러리에서 사진을 선택하세요.", type=["jpg", "jpeg", "png"])
    
    if uploaded_file is not None:
        if st.button("🚀 선택한 시설물에 사진 등록", type="secondary"):
            with st.spinner("구글 스토리지 서버로 고화질 이미지 전송 중..."):
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_name = f"infra_photos/{target_facility}_{timestamp}.png"
                    
                    # 1. Firebase Storage에 사진 업로드
                    blob = bucket.blob(file_name)
                    blob.upload_from_string(uploaded_file.read(), content_type="image/png")
                    blob.make_public()
                    public_url = blob.public_url
                    
                    # 2. [버그 해결!] 한글 이름으로 DB를 검색하는 대신, 엑셀 표에서 고유 영문 ID를 직접 찾아 매핑
                    target_row = edited_df[edited_df["시설물명"] == target_facility]
                    
                    if not target_row.empty:
                        target_doc_id = str(target_row.iloc[0]["doc_id"])
                        
                        # 아직 DB에 저장이 안 된 임시 데이터(sample 등)인 경우 차단
                        if target_doc_id in ["", "nan", "None", "<NA>"] or target_doc_id.startswith("sample"):
                            st.warning("엑셀 표에서 먼저 '💾 변경사항 저장' 버튼을 눌러 해당 시설물을 DB에 등록한 후 사진을 올려주세요.")
                        else:
                            # 오류를 뿜던 where() 검색 기능을 버리고, 고유 ID(target_doc_id)로 다이렉트 업데이트
                            db.collection("infra_management").document(target_doc_id).update({
                                "사진URL": public_url
                            })
                            st.success(f"🎉 {target_facility}에 사진 등록 및 엑셀 주소 매핑이 완료되었습니다!")
                            st.cache_data.clear()
                            st.rerun()
                            
                except Exception as e:
                    st.error(f"사진 매핑 실패: {e}")
else:
    st.info("엑셀 그리드에 시설물을 먼저 입력하고 저장해 주세요.")
