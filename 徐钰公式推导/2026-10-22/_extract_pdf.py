import pymupdf

p = r"E:\厉不厉害你贤哥\xwechat_files\wxid_gtirqowconi422_4a0e\msg\file\2026-10\Robonaut2灵巧手_论文专利精读与译文（含附录A-B）.pdf"
doc = pymupdf.open(p)
out = []
for i, page in enumerate(doc):
    out.append(f"\n===== PAGE {i+1} =====\n")
    out.append(page.get_text("text"))
text = "".join(out)
open(r"E:\SLAHAND\mmhand_wrist_control_1.0\徐钰公式推导\2026-10-22\_robonaut2_text.txt", "w", encoding="utf-8").write(text)
print("pages", len(doc), "chars", len(text))
print(text[:1500])
