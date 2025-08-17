from PyPDF2 import PdfReader, PdfWriter
from config import PDF_FILE
def fuse_in_pairs(input_pdf_path: str, output_pdf_path: str):
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()

    total_pages = len(reader.pages)
    # Parcours par pas de 2 : (0,1), (2,3), (4,5), ...
    for i in range(0, total_pages, 2):
        base_page = reader.pages[i]
        # Si la page suivante existe, on la fusionne
        if i + 1 < total_pages:
            overlay_page = reader.pages[i + 1]
            base_page.merge_page(overlay_page)

        # Ajout de la page fusionnée (ou seule, si impaire)
        writer.add_page(base_page)

    # Écriture du PDF de sortie
    with open(output_pdf_path, "wb") as out_f:
        writer.write(out_f)

if __name__ == "__main__":
    input_pdf  = PDF_FILE
    output_pdf = "fused_pairs.pdf"
    fuse_in_pairs(input_pdf, output_pdf)
    print(f"PDF généré avec pages fusionnées deux à deux : {output_pdf}")
