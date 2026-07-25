import os
import re

intelligence_dir = r"C:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices\src\components\intelligence"

for filename in os.listdir(intelligence_dir):
    if filename.endswith('.tsx'):
        filepath = os.path.join(intelligence_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix "use client" directive - remove any malformed versions and add correct one
        content = re.sub(r'^[^"]*"use client"', '"use client"', content)
        content = re.sub(r'^import React from "react";\s*', '', content)
        content = re.sub(r'^import React from "react";\r\n', '', content)
        
        # Ensure "use client" is at the very top
        if not content.startswith('"use client"'):
            content = '"use client"\n' + content
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed {filename}")

print("Done fixing intelligence panel files")