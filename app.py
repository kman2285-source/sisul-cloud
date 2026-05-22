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
        total_mb = 5120.0  # 5GB 무료 한도
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
@st.cache_data(ttl=3)
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
st.caption("💡 엑셀처럼 여러 행을 마우스로 드래그 선택한 뒤 키보드의 Delete 키를 누르면, 클라우드 DB와 사진 파일이 동시 삭제됩니다.")

# 3. 엑셀 형태의 인터랙티브 데이터 에디터 UI
edited_df = st.data_editor(
    df,
    column_order=["시설물명", "상태", "점검자", "최종점검일", "사진URL"],
    column_config={
        "doc_id": None,
        "상태": st.column_config.SelectboxColumn("상태", options=["정상", "점검필요", "정비중", "조치완료"], required=True),
        
        # 🎯 [핵심 개선] disabled=True 를 추가하여 모바일 터치 시 글자 수정 모드로 빠지는 현상을 완벽 차단합니다!
        "사진URL": st.column_config.LinkColumn("현장사진 링크", display_text="📸 사진 보기", disabled=True),
        
        "최종점검일": st.column_config.DateColumn("최종점검일", default=datetime.now().date())
    },
    num_rows="dynamic",
    use_container_width=True,
    key="infra_table_editor"
)

# 4. 사용자가 수정한 변화(수정, 추가, 삭제)를 감지하여 실시간으로 Firebase 동기화
if "infra_table_editor" in st.session_state:
    editor_state = st.session_state["infra_table_editor"]
    has_changes = False
    
    # A. 셀 내용이 수정되었을 때
    if editor_state.get("edited_rows"):
        for row_idx, changes in editor_state["edited_rows"].items():
            doc_id = df.iloc[int(row_idx)]["doc_id"]
            
            if str(doc_id).startswith("sample"):
                row_full = df.iloc[int(row_idx)].to_dict()
                row_full.update(changes)
                row_data = {
                    "시설물명": row_full.get("시설물명", "이름 없음"),
                    "상태": row_full.get("상태", "정상"),
                    "점검자": row_full.get("점검자", "미지정"),
                    "사진URL": row_full.get("사진URL", ""),
                    "최종점검일": str(row_full.get("최종점검일", datetime.now().date()))
                }
                db.collection("infra_management").add(row_data)
            else:
                if "최종점검일" in changes:
                    changes["최종점검일"] = str(changes["최종점검일"])
                db.collection("infra_management").document(str(doc_id)).update(changes)
        has_changes = True
                
    # B. 새로운 시설물 행이 추가되었을 때
    if editor_state.get("added_rows"):
        for row in editor_state["added_rows"]:
            row_data = {
                "시설물명": row.get("시설물명", "이름 없음"),
                "상태": row.get("상태", "정상"),
                "점검자": row.get("점검자", "미지정"),
                "사진URL": row.get("사진URL", ""),
                "최종점검일": str(row.get("최종점검일", datetime.now().date()))
            }
            db.collection("infra_management").add(row_data)
        has_changes = True
            
    # C. 행을 삭제했을 때 (DB + 원본 사진 동시 파기)
    if editor_state.get("deleted_rows"):
        for row_idx in editor_state["deleted_rows"]:
            doc_id = df.iloc[int(row_idx)]["doc_id"]
            
            if not str(doc_id).startswith("sample"):
                try:
                    doc_ref = db.collection("infra_management").document(str(doc_id))
                    doc_snap = doc_ref.get()
                    
                    if doc_snap.exists:
                        doc_data = doc_snap.to_dict()
                        photo_url = doc_data.get("사진URL", "")
                        
                        if photo_url:
                            bucket_domain = "sisul-2026.firebasestorage.app/"
                            if bucket_domain in photo_url:
                                blob_name = photo_url.split(bucket_domain)[-1]
                                try:
                                    bucket.blob(blob_name).delete()
                                except Exception:
                                    pass
                    doc_ref.delete()
                except Exception as e:
                    st.error(f"실시간 데이터 파기 실패: {e}")
        has_changes = True
                
    if has_changes:
        st.cache_data.clear()
        st.rerun()

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
                    
                    blob = bucket.blob(file_name)
                    blob.upload_from_string(uploaded_file.read(), content_type="image/png")
                    blob.make_public()
                    public_url = blob.public_url
                    
                    target_row = edited_df[edited_df["시설물명"] == target_facility]
                    
                    if not target_row.empty:
                        target_doc_id = str(target_row.iloc[0]["doc_id"])
                        
                        if target_doc_id in ["", "nan", "None", "<NA>"] or target_doc_id.startswith("sample"):
                            st.warning("시설물명을 먼저 입력하신 후, 셀 바깥을 클릭하여 DB에 자동 등록된 상태에서 사진을 올려주세요.")
                        else:
                            db.collection("infra_management").document(target_doc_id).update({
                                "사진URL": public_url
                            })
                            st.success(f"🎉 {target_facility}에 사진 등록 및 실시간 매핑이 완료되었습니다!")
                            st.cache_data.clear()
                            st.rerun()
                            
                except Exception as e:
                    st.error(f"사진 매핑 실패: {e}")
else:
    st.info("엑셀 그리드에 시설물을 먼저 입력해 주세요.")
