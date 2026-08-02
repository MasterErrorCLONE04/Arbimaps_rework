import sys
import os

input_file = '/home/roobot/Develop/ubuntu/download/neiva.sql'
output_file = '/home/roobot/Develop/ubuntu/download/neiva_renamed.sql'

print(f"Renaming schemas in {input_file}...")

try:
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"File not found: {input_file}")

    # Read and write line-by-line to avoid loading the entire 900+ MB file into memory
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f_in, open(output_file, 'w', encoding='utf-8') as f_out:
        for i, line in enumerate(f_in):
            # Replace plugin_v7 with a_base_principal
            line = line.replace('plugin_v7', 'a_base_principal')
            # Replace cartografia_catastral_v2 with c_cartografia_catastral
            line = line.replace('cartografia_catastral_v2', 'c_cartografia_catastral')
            f_out.write(line)
            if i % 1000000 == 0 and i > 0:
                print(f"Processed {i} lines...")
    
    # Overwrite the original file with the renamed version
    os.replace(output_file, input_file)
    print("Success! Original file has been updated with the new schema names.")

except Exception as e:
    print(f"Error occurred: {e}")
    if os.path.exists(output_file):
        try:
            os.remove(output_file)
        except Exception:
            pass
    sys.exit(1)
