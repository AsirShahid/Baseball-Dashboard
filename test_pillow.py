from PIL import Image
print("Pillow imported successfully")
img = Image.new('RGB', (60, 30), color = (73, 109, 137))
img.save('test.png')
print("Image created and saved successfully")