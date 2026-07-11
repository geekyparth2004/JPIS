import os
import glob
from PIL import Image, ImageDraw, ImageFont

# Find all jpegs
images = glob.glob('assets/**/*.jpeg', recursive=True) + glob.glob('assets/**/*.jpg', recursive=True)

# We will create an image with max 10 images per row
cols = 5
rows = (len(images) + cols - 1) // cols
thumb_width = 300
thumb_height = 300

contact_sheet = Image.new('RGB', (cols * thumb_width, rows * thumb_height), (255, 255, 255))
draw = ImageDraw.Draw(contact_sheet)

for i, img_path in enumerate(images):
    try:
        img = Image.open(img_path)
        img.thumbnail((thumb_width, thumb_height - 30))
        
        x = (i % cols) * thumb_width
        y = (i // cols) * thumb_height
        
        # Paste image centered
        offset_x = x + (thumb_width - img.width) // 2
        offset_y = y + (thumb_height - 30 - img.height) // 2
        contact_sheet.paste(img, (offset_x, offset_y))
        
        # Draw filename
        filename = os.path.basename(img_path)
        draw.text((x + 10, y + thumb_height - 20), filename, fill=(0, 0, 0))
    except Exception as e:
        print(f"Failed to process {img_path}: {e}")

contact_sheet.save('tmp/new-potos-contact-sheet.jpg')
print("Saved tmp/new-potos-contact-sheet.jpg")
