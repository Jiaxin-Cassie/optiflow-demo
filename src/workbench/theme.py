"""Streamlit adaptation of the editable OptiFlow Figma foundations."""
import streamlit as st


def apply_theme():
    st.html("""<style>
:root{--of-brand:#6554c0;--of-ink:#202334;--of-muted:#5e6475;--of-border:#dde0e8;}
.stApp{background:#f7f8fa;color:var(--of-ink);font-family:'Noto Sans SC','Microsoft YaHei',sans-serif;}
.block-container{max-width:1216px;padding:3.5rem 3rem 4rem;}
h1{font-size:28px!important;line-height:1.45!important;letter-spacing:0!important;font-weight:700!important;margin-bottom:8px!important;}
h2,h3{font-size:20px!important;line-height:1.5!important;letter-spacing:0!important;}
p,li,[data-testid="stMarkdownContainer"] p,[data-testid="stWidgetLabel"] p{font-size:16px!important;line-height:1.7!important;}
[data-testid="stCaptionContainer"] p,small,.source,.sub,.stage-note,.stage-state,.quantity-caption,.quantity-axis,.quantity-unit,.footer{font-size:14px!important;color:var(--of-muted)!important;line-height:1.65!important;}
[data-testid="stSidebar"]{background:#fff;border-right:1px solid var(--of-border);}
[data-testid="stSidebar"][aria-expanded="true"]{width:224px!important;min-width:224px!important;max-width:224px!important;}
[data-testid="stSidebar"][aria-expanded="false"]{min-width:0!important;max-width:0!important;}
[data-testid="stSidebar"] *{color:var(--of-ink);}
[data-testid="stSidebar"] .stButton button{justify-content:flex-start;min-height:48px;background:#fff;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *{color:var(--of-muted)!important;}
[data-testid="stSidebar"] .stButton button p{font-size:16px!important;}
.stApp div[data-testid="stCaptionContainer"],.stApp div[data-testid="stCaptionContainer"] *,.stApp [data-testid="stSidebar"] [data-testid="stCaptionContainer"] *{font-size:14px!important;color:#5e6475!important;line-height:1.65!important;}
.stApp [data-testid="stCaptionContainer"]{opacity:1!important;}
.stButton button,.stDownloadButton button,[data-testid="stFormSubmitButton"] button{min-height:48px;border-radius:8px!important;border-color:var(--of-border);padding:10px 20px;white-space:normal;}
.stButton button[kind="primary"],[data-testid="stFormSubmitButton"] button[kind="primary"]{background:#6554c0;border-color:#6554c0;color:white;}
button:focus-visible{outline:3px solid #afa2e8!important;outline-offset:3px;}
textarea,input{font-size:16px!important;line-height:1.7!important;}
[data-testid="stVerticalBlockBorderWrapper"]{background:white;border-radius:12px;border-color:var(--of-border)!important;overflow:visible;}
[data-testid="stMetric"]{background:#fff;border:0;padding:12px 0;min-height:100px;height:auto!important;overflow:visible;}
[data-testid="stMetricValue"]{font-size:32px;line-height:1.4;letter-spacing:0;overflow-wrap:anywhere;}
.stApp [data-testid="stMetricValue"] *{font-size:32px!important;line-height:1.4!important;}
.st-key-of-input-card,.st-key-of-business-card,.st-key-of-model-card,.st-key-of-modify-card,.st-key-of-feedback-card,.st-key-decision-brief-workspace-v2{background:#fff;border:1px solid #dde0e8!important;border-radius:12px;padding:24px!important;}
[data-testid="stAppDeployButton"]{display:none;}
[data-testid="stMetricLabel"]{color:var(--of-muted);}
.of-brand{font-size:24px;font-weight:700;color:#6554c0;margin-bottom:8px;}
.of-kicker{font-size:14px;color:#5e6475;margin:0 0 18px;}
.of-step{background:#fff;border:1px solid #dde0e8;border-radius:12px;padding:24px;min-height:155px;}
.of-step b{display:block;margin:12px 0 8px;font-size:20px;}.of-step span{color:#6554c0;font-size:20px;}
.of-step p{color:#5e6475;font-size:14px!important;}
.of-guide{margin:20px 0;color:#5e6475;}
.st-key-of-stepnav{margin:0 0 24px;}
.st-key-of-stepnav [data-testid="stHorizontalBlock"]{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;}
.st-key-of-stepnav [data-testid="stColumn"]{width:100%!important;min-width:0!important;}
.st-key-of-stepnav button{padding:8px;}
.of-active-step{color:#6554c0;font-weight:700;}
.stAlert{border-radius:10px;}
.eyebrow,.case-no{color:#6554c0;font-size:14px;letter-spacing:0;}
.quantity-chart{box-sizing:border-box;background:#fff;border:1px solid #dde0e8;border-radius:12px;padding:24px;overflow:visible;}
.quantity-title{font-size:20px;}.quantity-row-heading>span{font-size:16px;}.quantity-row-heading strong{font-size:28px;}
@media(max-width:850px){.block-container{padding:3rem 1.25rem;}.stApp [data-testid="stMetricValue"] *{font-size:26px!important;}}
@media(max-width:550px){h1{font-size:26px!important;}.st-key-of-stepnav [data-testid="stHorizontalBlock"]{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}.of-step{min-height:0;padding:18px;}}
</style>""")
