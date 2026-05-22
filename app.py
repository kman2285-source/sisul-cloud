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

# ☁️ 좌측 사이드바 용량 표시
with st.sidebar:
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

# 2. Firebase 데이터 불러오기 및 정렬
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
            {"doc_id": "sample1", "시설물명": "신천대로 교량 A지점", "상태": "정상", "점검자": "관리자", "사진URL": "", "최종점검일": "2026-05-22", "등록일시": "2026-01-01 00:00:00"},
            {"doc_id": "sample2", "시설물명": "범어 지하차도 배수펌프", "상태": "점검필요", "점검자": "관리자", "사진URL": "", "최종점검일": "2026-05-22", "등록일시": "2026-01-01 00:00:01"}
        ]
        return pd.DataFrame(initial_data)
    
    df_temp = pd.DataFrame(data_list)
    if "등록일시" not in df_temp.columns:
        df_temp["등록일시"] = "2000-01-01 00:00:00"
    df_temp["등록일시"] = df_temp["등록일시"].fillna("2000-01-01 00:00:00")
    df_temp = df_temp.sort_values("등록일시", ascending=True).reset_index(drop=True)
    return df_temp

try:
    df = load_infra_data()
    if "최종점검일" in df.columns:
        df["최종점검일"] = pd.to_datetime(df["최종점검일"], errors="coerce").dt.date
except Exception as e:
    df = pd.DataFrame(columns=["doc_id", "시설물명", "상태", "점검자", "사진URL", "최종점검일", "등록일시"])
    df["최종점검일"] = pd.to_datetime(df["최종점검일"]).dt.date

# ⚙️ 관리 메뉴 (항목 추가 및 이름 변경)
col_mgmt1, col_mgmt2 = st.columns(2)

with col_mgmt1:
    with st.expander("⚙️ 표 항목(열) 추가하기"):
        with st.form("add_column_form", clear_on_submit=True):
            st.caption("비고, 연락처 등 새롭게 추가하고 싶은 항목 이름을 적어주세요.")
            new_col_name = st.text_input("새 항목 이름", placeholder="예: 비고")
            submitted = st.form_submit_button("➕ 항목 추가")
            
            if submitted and new_col_name:
                new_col_name = new_col_name.strip()
                if new_col_name in df.columns:
                    st.warning("이미 존재하는 항목입니다.")
                elif new_col_name in ["doc_id", "등록일시"]:
                    st.error("시스템 예약어는 사용할 수 없습니다.")
                else:
                    with st.spinner("클라우드 DB에 새 항목을 추가하는 중..."):
                        docs = db.collection("infra_management").stream()
                        for doc in docs:
                            doc.reference.update({new_col_name: ""})
                        st.success(f"'{new_col_name}' 항목이 표에 추가되었습니다!")
                        st.cache_data.clear()
                        st.rerun()

with col_mgmt2:
    with st.expander("📝 표 항목(열) 이름 변경하기"):
        custom_cols = [c for c in df.columns if c not in ["doc_id", "등록일시", "시설물명", "상태", "점검자", "최종점검일", "사진URL"]]
        
        if not custom_cols:
            st.caption("💡 현재 이름을 바꿀 수 있는 커스텀 항목이 없습니다. 먼저 항목을 추가해 주세요.")
        else:
            with st.form("rename_column_form", clear_on_submit=True):
                st.caption("기존에 추가했던 항목의 이름을 새 이름으로 변경합니다.")
                old_name = st.selectbox("변경할 기존 항목 선택", custom_cols)
                new_name = st.text_input("새로운 항목 이름", placeholder="예: 비고_수정")
                rename_submitted = st.form_submit_button("✏️ 이름 변경 적용")
                
                if rename_submitted and old_name and new_name:
                    new_name = new_name.strip()
                    if new_name in df.columns:
                        st.warning("이미 표에 존재하는 항목 이름입니다.")
                    elif new_name in ["doc_id", "등록일시"]:
                        st.error("시스템 예약어는 사용할 수 없습니다.")
                    else:
                        with st.spinner("클라우드 데이터 이전 및 이름 변경 중..."):
                            docs = db.collection("infra_management").stream()
                            for doc in docs:
                                doc_data = doc.to_dict()
                                if old_name in doc_data:
                                    doc.reference.update({
                                        new_name: doc_data[old_name],
                                        old_name: firestore.DELETE_FIELD
                                    })
                            st.success(f"'{old_name}' 항목이 '{new_name}'(으)로 일괄 변경되었습니다!")
                            st.cache_data.clear()
                            st.rerun()

st.subheader("📊 인프라 자산 관리 그리드 (엑셀 형태)")
st.caption("💡 **[삭제 방법]** 모바일에서는 왼쪽의 체크박스를 여러 개 선택하거나, PC에서는 마우스 드래그 후 키보드의 **Delete** 키를 누르면 클라우드 DB와 사진이 동시 삭제됩니다.")

# 🎯 [핵심 수정] 커스텀 열 이름들을 가나다순으로 강력하게 정렬(sorted)하여 NoSQL의 랜덤 섞임을 원천 차단합니다.
base_cols = ["시설물명", "상태", "점검자", "최종점검일", "사진URL"]
for col in base_cols:
    if col not in df.columns:
        df[col] = ""

# sorted() 함수를 씌워 추가된 열들이 무조건 고정된 순서로 나타나게 만듭니다.
extra_cols = sorted([c for c in df.columns if c not in base_cols + ["doc_id", "등록일시"]])
final_column_order = base_cols + extra_cols
df = df[["doc_id", "등록일시"] + final_column_order]

# 3. 엑셀 형태 UI (모바일 최적화)
edited_df = st.data_editor(
    df,
    column_order=final_column_order,
    column_config={
        "doc_id": None,
        "등록일시": None,
        "상태": st.column_config.SelectboxColumn("상태", options=["정상", "점검필요", "정비중", "조치완료"], required=True),
        "사진URL": st.column_config.LinkColumn("현장사진 링크", display_text="📸 사진 보기", disabled=True),
        "최종점검일": st.column_config.DateColumn("최종점검일", default=datetime.now().date())
    },
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,  # 🎯 모바일 화면을 낭비하던 맨 왼쪽 행 번호(0,1,2)를 깔끔하게 숨깁니다.
    key="infra_table_editor"
)

# 4. 실시간 동기화
if "infra_table_editor" in st.session_state:
    editor_state = st.session_state["infra_table_editor"]
    has_changes = False
    
    if editor_state.get("edited_rows"):
        for row_idx, changes in editor_state["edited_rows"].items():
            doc_id = df.iloc[int(row_idx)]["doc_id"]
            if str(doc_id).startswith("sample"):
                row_full = df.iloc[int(row_idx)].to_dict()
                row_full.update(changes)
                if "doc_id" in row_full: del row_full["doc_id"]
                row_full["최종점검일"] = str(row_full.get("최종점검일", datetime.now().date()))
                row_full["등록일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                row_full = {k: ("" if pd.isna(v) else v) for k, v in row_full.items()}
                db.collection("infra_management").add(row_full)
            else:
                if "최종점검일" in changes:
                    changes["최종점검일"] = str(changes["최종점검일"])
                db.collection("infra_management").document(str(doc_id)).update(changes)
        has_changes = True
                
    if editor_state.get("added_rows"):
        for row in editor_state["added_rows"]:
            row_data = row.copy()
            row_data["최종점검일"] = str(row_data.get("최종점검일", datetime.now().date()))
            row_data["등록일시"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
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
                        photo_url = doc_snap.to_dict().get("사진URL", "")
                        if photo_url and "sisul-2026.firebasestorage.app/" in photo_url:
                            blob_name = photo_url.split("sisul-2026.firebasestorage.app/")[-1]
                            try:
                                bucket.blob(blob_name).delete()
                            except Exception: pass
                    doc_ref.delete()
                except Exception as e:
                    st.error(f"데이터 파기 실패: {e}")
        has_changes = True
                
    if has_changes:
        st.cache_data.clear()
        st.rerun()

st.markdown("---")

# 5. 모바일 현장 사진 업로드
st.subheader("📸 모바일 현장 점검 사진 등록")

facility_list = edited_df["시설물명"].dropna().unique()
if len(facility_list) > 0:
    target_facility = st.selectbox("사진을 매핑할 시설물을 선택하세요:", facility_list)
    uploaded_file = st.file_uploader("스마트폰 카메라로 촬영하거나 갤러리에서 사진을 선택하세요.", type=["jpg", "jpeg", "png"])
    
    if uploaded_file is not None:
        if st.button("🚀 선택한 시설물에 사진 등록", type="secondary"):
            with st.spinner("이미지 전송 중..."):
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
                            db.collection("infra_management").document(target_doc_id).update({"사진URL": public_url})
                            st.success(f"🎉 {target_facility}에 사진 등록 및 실시간 매핑 완료!")
                            st.cache_data.clear()
                            st.rerun()
                except Exception as e:
                    st.error(f"사진 매핑 실패: {e}")
else:
    st.info("엑셀 그리드에 시설물을 먼저 입력해 주세요.")
