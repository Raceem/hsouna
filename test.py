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

    date_matrix = [
        ["5/07",  "4/07",  "3/07",  "2/07",  "1/07",  "", ""],
        ["12/07",  "11/07",  "10/07",  "09/07",  "8/07",  "7/07",  "6/07"],
        ["19/07", "18/07", "17/07", "16/07", "15/07", "14/07", "13/07"],
        ["20/07", "21/07", "22/07", "23/07", "24/07", "25/07", "26/07"],
        ["27/07", "28/07", "29/07", "30/07", "31/07", "", ""]
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
