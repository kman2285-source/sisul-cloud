import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore, storage
import json
from datetime import datetime
import streamlit.components.v1 as components

# 페이지 기본 설정
st.set_page_config(page_title="스마트 인프라 관리 시스템", layout="wide")

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

# 클라우드 DB에서 열 순서 불러오기
settings_ref = db.collection("system").document("settings")
settings_snap = settings_ref.get()

if not settings_snap.exists:
    initial_order = ["시설물명", "상태", "점검자", "최종점검일", "사진URL", "시설물 위치"]
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
        data_list.append(d)
    
    if not data_list:
        return pd.DataFrame([{"doc_id": "sample1", "시설물명": "신천대로 교량 A지점", "상태": "정상", "점검자": "관리자", "사진URL": "", "최종점검일": "2026-05-22", "등록일시": "2026-01-01 00:00:00", "시설물 위치": ""}])
    
    df_temp = pd.DataFrame(data_list)
    if "등록일시" not in df_temp.columns:
        df_temp["등록일시"] = "2000-01-01 00:00:00"
    df_temp["등록일시"] = df_temp["등록일시"].fillna("2000-01-01 00:00:00")
    return df_temp.sort_values("등록일시", ascending=True).reset_index(drop=True)

df = load_infra_data()

# DB 데이터와 설정된 열 순서 동기화
for c in col_order:
    if c not in df.columns:
        df[c] = ""
        
rogue_cols = [c for c in df.columns if c not in col_order and c not in ["doc_id", "등록일시"]]
if rogue_cols:
    col_order.extend(rogue_cols)
    settings_ref.update({"column_order": col_order})

df = df[["doc_id", "등록일시"] + col_order]

date_cols = [c for c in col_order if "일" in c or "날짜" in c]
for dc in date_cols:
    df[dc] = pd.to_datetime(df[dc], errors="coerce").dt.date

# 🎯 [핵심 버그 수정] 컴퓨터 내부 인덱스는 건드리지 않고, 맨 앞에 가짜 'NO' 열을 물리적으로 끼워 넣습니다.
df.insert(0, "NO", range(1, len(df) + 1))
display_order = ["NO"] + col_order # 화면에 보여줄 순서 정의

# ⚙️ 관리 메뉴 
st.subheader("⚙️ 표 기본 설정 관리")
tab1, tab2, tab3 = st.tabs(["➕ 항목(열) 추가", "📝 이름 일괄 변경", "↔️ 열 순서 영구 고정"])

with tab1:
    with st.form("add_column_form", clear_on_submit=True):
        new_col_name = st.text_input("새 항목 이름", placeholder="예: 점검 내용")
        if st.form_submit_button("➕ 항목 추가") and new_col_name:
            new_col_name = new_col_name.strip()
            if new_col_name in df.columns: 
                st.warning("이미 존재합니다.")
            elif new_col_name in ["doc_id", "등록일시", "NO"]: 
                st.error("시스템 예약어는 사용할 수 없습니다.")
            else:
                with st.spinner("항목 추가 중..."):
                    docs = db.collection("infra_management").stream()
                    for doc in docs: doc.reference.update({new_col_name: ""})
                    col_order.append(new_col_name)
                    settings_ref.update({"column_order": col_order})
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
            st.cache_data.clear()
            st.rerun()

st.markdown("---")

# 안내 문구 최적화
col_title, col_save = st.columns([7, 3])
with col_title:
    st.subheader("📊 인프라 자산 관리 그리드 (엑셀 형태)")
    st.caption("💡 **Tip:** 표 우측 상단의 확대(⛶)로 넓게 작업하신 후, **축소(ESC)해서 우측 [일괄 저장]**을 누르세요. 창을 줄여도 작성한 내용은 유지됩니다!")
with col_save:
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    save_btn = st.button("💾 변경사항 서버에 일괄 저장", use_container_width=True, type="primary")

for c in col_order:
    if any(keyword in c for keyword in ["사진", "URL", "링크", "위치", "지도"]):
        df[c] = df[c].map(lambda x: None if pd.isna(x) or str(x).strip() == "" else x)

# 맞춤형 열 서식 지정
dynamic_config = {
    "doc_id": None, 
    "등록일시": None,
    "NO": st.column_config.NumberColumn("NO", disabled=True) # 수정 불가하게 잠금
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

# 3. 엑셀 형태 UI
edited_df = st.data_editor(
    df,
    column_order=display_order, # 가짜 NO가 포함된 순서 적용
    column_config=dynamic_config,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True, # 진짜 인덱스는 숨김 (안전)
    key="infra_table_editor"
)

# 📥 엑셀 다운로드 
st.markdown(" ") 
export_df = edited_df[display_order].copy()
csv_data = export_df.to_csv(index=False).encode('utf-8-sig')

st.download_button(
    label="📥 현재 표 데이터 다운로드 (Excel 호환)",
    data=csv_data,
    file_name=f"인프라_인벤토리_현황_{datetime.now().strftime('%Y%m%d')}.csv",
    mime="text/csv",
    use_container_width=True,
    type="secondary"
)

# 4. 수동 일괄 저장 로직 (인덱스 불일치 버그 100% 차단)
if save_btn:
    editor_state = st.session_state.get("infra_table_editor", {})
    has_changes = False
    
    if editor_state.get("edited_rows"):
        for row_idx, changes in editor_state["edited_rows"].items():
            # 🎯 loc 대신 iloc(절대 위치)를 사용하여 정확한 행을 타겟팅합니다.
            doc_id = df.iloc[int(row_idx)]["doc_id"]
            
            # 가짜 NO 열은 DB에 저장되지 않도록 삭제
            if "NO" in changes: del changes["NO"]
            
            for k, v in list(changes.items()):
                if isinstance(v, type(datetime.now().date())):
                    changes[k] = str(v)
                
                if ("위치" in k or "지도" in k) and v:
                    val_str = str(v).strip()
                    if not (val_str.startswith("http://") or val_str.startswith("https://")):
                        changes[k] = f"https://www.google.com/maps/search/?api=1&query={val_str}"

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
                        row_data[k] = f"https://www.google.com/maps/search/?api=1&query={val_str}"
                        
            row_data = {k: ("" if pd.isna(v) else v) for k, v in row_data.items()}
            db.collection("infra_management").add(row_data)
        has_changes = True
            
    if editor_state.get("deleted_rows"):
        for row_idx in editor_state["deleted_rows"]:
            # 🎯 엉뚱한 행이 지워지는 버그의 원인 차단! 절대 위치(iloc)로 타겟팅.
            doc_id = df.iloc[int(row_idx)]["doc_id"]
            if not str(doc_id).startswith("sample"):
                try:
                    doc_ref = db.collection("infra_management").document(str(doc_id))
                    doc_snap = doc_ref.get()
                    if doc_snap.exists:
                        doc_data = doc_snap.to_dict()
                        photo_col_name = next((c for c in col_order if "사진" in c or "URL" in c or "링크" in c), None)
                        if photo_col_name:
                            photo_url = doc_data.get(photo_col_name, "")
                            if photo_url and "sisul-2026.firebasestorage.app/" in photo_url:
                                blob_name = photo_url.split("sisul-2026.firebasestorage.app/")[-1]
                                try: bucket.blob(blob_name).delete()
                                except Exception: pass
                    doc_ref.delete()
                except Exception as e:
                    pass
        has_changes = True
                
    if has_changes:
        st.cache_data.clear()
        st.success("🎉 작성하신 모든 내용이 클라우드에 안전하게 일괄 저장되었습니다!")
        st.rerun()
    else:
        st.info("새로 변경되거나 추가된 내용이 없습니다.")

st.markdown("---")

# 5. 모바일 현장 사진 업로드
st.subheader("📸 모바일 현장 점검 사진 등록")

main_col = col_order[0] 
photo_col = next((c for c in col_order if "사진" in c or "URL" in c or "링크" in c), None)

if photo_col:
    facility_list = edited_df[main_col].dropna().unique()
    if len(facility_list) > 0:
        target_facility = st.selectbox(f"사진을 매핑할 [{main_col}]을(를) 선택하세요:", facility_list)
        uploaded_file = st.file_uploader("스마트폰 카메라로 촬영하거나 갤러리에서 사진을 선택하세요.", type=["jpg", "jpeg", "png"])
        
        if uploaded_file is not None:
            if st.button(f"🚀 선택한 [{main_col}]에 사진 등록", type="secondary"):
                with st.spinner("이미지 전송 중..."):
                    try:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        file_name = f"infra_photos/{target_facility}_{timestamp}.png"
                        
                        blob = bucket.blob(file_name)
                        blob.upload_from_string(uploaded_file.read(), content_type="image/png")
                        blob.make_public()
                        public_url = blob.public_url
                        
                        target_row = edited_df[edited_df[main_col] == target_facility]
                        if not target_row.empty:
                            target_doc_id = str(target_row.iloc[0]["doc_id"])
                            if target_doc_id in ["", "nan", "None", "<NA>"] or target_doc_id.startswith("sample"):
                                st.warning("먼저 입력하신 후, 셀 바깥을 클릭하여 DB에 자동 등록된 상태에서 사진을 올려주세요.")
                            else:
                                db.collection("infra_management").document(target_doc_id).update({photo_col: public_url})
                                st.success(f"🎉 {target_facility}에 사진 등록 및 실시간 매핑 완료!")
                                st.cache_data.clear()
                                st.rerun()
                    except Exception as e:
                        st.error(f"사진 매핑 실패: {e}")
    else:
        st.info(f"엑셀 그리드에 [{main_col}]을(를) 먼저 입력해 주세요.")
else:
    st.warning("이름에 '사진', 'URL', '링크' 중 하나가 포함된 항목(열)이 있어야 사진을 매핑할 수 있습니다.")
