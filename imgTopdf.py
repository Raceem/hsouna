from PIL import Image
import os

# 📁 Dossier contenant les images
image_folder = "C:/Users/lenovo/Desktop/riadh/omra/iraq/rawdha"  # Remplace par le nom de ton dossier
output_pdf = "C:/Users/lenovo/Desktop/riadh/omra/iraq/rawdha/resultat.pdf"

# 📷 Extensions d'images autorisées
image_extensions = (".jpg", ".jpeg", ".png")

# 📂 Liste des fichiers image dans le dossier
image_files = [f for f in os.listdir(image_folder) if f.lower().endswith(image_extensions)]
image_files.sort()  # Pour garder l’ordre

# 📚 Charger les images
images = []
for filename in image_files:
    img_path = os.path.join(image_folder, filename)
    image = Image.open(img_path).convert("RGB")
    images.append(image)

# 🖨️ Sauvegarder en PDF
if images:
    images[0].save(output_pdf, save_all=True, append_images=images[1:])
    print(f"✅ PDF créé avec succès : {output_pdf}")
else:
    print("❌ Aucune image trouvée.")
