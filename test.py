import cv2
import numpy as np
import matplotlib.pyplot as plt
import os

def date_available(pathScreen, output_path="output_with_grid.jpg"):
    # Charger l'image originale
    image_path = pathScreen
    image = cv2.imread(image_path)

    # Définir la région du calendrier
    x_offset, y_offset, w, h = 100, 550, 900, 1150
    calendar = image[y_offset:y_offset+h, x_offset:x_offset+w]
    height, width, _ = calendar.shape

    rows, cols = 5, 7
    cell_width = width / cols
    cell_height = height / rows
    cv2.imwrite("debug_crop.jpg", calendar)
    date_matrix = [
            ["",  "",  "",  "",  "",  "01/08", "02/08"],
            ["03/08",  "04/08",  "05/08",  "06/08",  "07/08",  "08/08",  "09/08"],
            ["10/08", "11/08", "12/08", "13/08", "14/08", "15/08", "16/08"],
            ["17/08", "18/08", "19/08", "20/08", "21/08", "22/08", "23/08"],
            ["24/08", "25/08", "26/08", "27/08", "28/08", "29/08", "30/08"]
        ]

    hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_green = np.array([35, 50, 50])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv_image, lower_green, upper_green)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    available_dates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        center_x = x + w // 2
        center_y = y + h // 2

        if x_offset <= center_x <= x_offset + width and y_offset <= center_y <= y_offset + height:
            rel_x = center_x - x_offset
            rel_y = center_y - y_offset
            col = int(rel_x / cell_width)
            row = int(rel_y / cell_height)
            date_value = date_matrix[row][col]
            available_dates.append((date_value, center_x, center_y))

            cv2.circle(image, (center_x, center_y), 5, (0, 0, 255), -1)
            cv2.putText(image, f"{date_value}", (center_x, center_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(image, f"({row+1},{col+1})", (center_x, center_y + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # ➕ Dessiner la grille sur la zone du calendrier
    for r in range(1, rows):
        y = y_offset + int(r * cell_height)
        cv2.line(image, (x_offset, y), (x_offset + width, y), (255, 0, 0), 1)
    for c in range(1, cols):
        x = x_offset + int(c * cell_width)
        cv2.line(image, (x, y_offset), (x, y_offset + height), (255, 0, 0), 1)

    # 💾 Enregistrer l’image annotée
    cv2.imwrite(output_path, image)
    print(f"\n✅ Image enregistrée avec la grille : {output_path}\n")

    # 🔍 Afficher les dates trouvées
    print("Dates disponibles détectées :")
    for date_value, orig_x, orig_y in sorted(available_dates):
        print(f"Date: {date_value} | Coordonnées originales: ({orig_x}, {orig_y})")

    return available_dates
