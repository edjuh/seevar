#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/auto_header.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Injects standardized file headers into Python scripts across the project.
"""

import os
import glob

def inject_headers(base_dir):
    search_pattern = os.path.join(base_dir, '**/*.py')
    py_files = glob.glob(search_pattern, recursive=True)
    fixed_count = 0

    for filepath in py_files:
        if any(x in filepath for x in ['venv', '.pyenv', '__pycache__']):
            continue
            
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            rel_path = os.path.relpath(filepath, base_dir)
            
            header = f"""#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"
Filename: {rel_path}
Version: 1.2.0 (Pee Pastinakel)
Objective: Standardized script header.
\"\"\"

"""
            clean_content = content.replace("#!/usr/bin/env python3\n", "").replace("# -*- coding: utf-8 -*-\n", "")
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(header + clean_content.lstrip())
            
            print(f"✅ Injected header into: {rel_path}")
            fixed_count += 1

    print(f"\nDone! Fixed {fixed_count} files.")

if __name__ == "__main__":
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    inject_headers(project_root)
