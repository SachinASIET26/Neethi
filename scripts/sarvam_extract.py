import os
import time
from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()

def test_sarvam_extraction():
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        print("SARVAM_API_KEY not found in environment")
        return

    client = SarvamAI(api_subscription_key=api_key)
    
    # Create a document intelligence job
    job = client.document_intelligence.create_job(
        language="hi-IN",
        output_format="md"
    )
    print(f"Job created: {job.job_id}")

    # Upload document
    pdf_path = r"C:\Projects\Phase2\Project Documents\bprd_bns_handbook.pdf"
    print(f"Uploading {pdf_path}")
    job.upload_file(pdf_path)
    print("File uploaded")

    # Start processing
    job.start()
    print("Job started")

    # Wait for completion
    status = job.wait_until_complete()
    print(f"Job completed with state: {status.job_state}")
    
    if status.job_state.upper() == "COMPLETED":
        # Get processing metrics
        metrics = job.get_page_metrics()
        print(f"Page metrics: {metrics}")

        # Download output (ZIP file containing the processed document)
        job.download_output("./sarvam_out_bns.zip")
        print("Output saved to ./sarvam_out_bns.zip")
    else:
        print("Job did not complete successfully.")

if __name__ == "__main__":
    test_sarvam_extraction()
