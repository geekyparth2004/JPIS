import glob

html_files = glob.glob('*.html')
target = '&quot;applyHref&quot;:&quot;04-integrated-navigation-for-admissions-page.html&quot;}, $emit() {} }">'
replacement = '&quot;applyHref&quot;:&quot;04-integrated-navigation-for-admissions-page.html&quot;,&quot;galleryHref&quot;:&quot;06-photo-gallery.html&quot;}, $emit() {} }">'

count = 0
for file in html_files:
    with open(file, 'r') as f:
        content = f.read()
    
    if target in content:
        new_content = content.replace(target, replacement)
        with open(file, 'w') as f:
            f.write(new_content)
        count += 1
        print(f"Updated {file}")

print(f"Total updated: {count}")
