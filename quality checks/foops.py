import json
import requests

foops_url = "https://foops.linkeddata.es/assessOntology"
headers = {"Content-Type": "application/json"}

payload = {
    "ontologyUri": "https://w3id.org/pmd/noes/"
}

response = requests.post(foops_url, json=payload, headers=headers)

# Ensure the request succeeded (HTTP 200)
if response.status_code == 200:
    try:
        data = response.json()
        
        # Save formatted JSON to a file
        output_filename = "foops_assessment.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except: 
        output_filename = "foops_assessment.html"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(response.text)
    
        
    print(f"FOOPS! report saved successfully to {output_filename}")
else:
    print(f"Failed with status code {response.status_code}: {response.text}")