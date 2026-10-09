# AI Auditor Knowledge Architecture Report - Run 2

Generated: 2026-10-06T11:11:38.446858+00:00

No files were moved, renamed, deleted, archived, or created by this run.

## Action Summary

- Findings in this run: 104
- Open actions overall: 0 high, 82 medium, 89 low
- Reviewed (accepted or rejected) to date: 0
- Registry suggestions can be applied in one step: `python -m auditor.cli bootstrap-registry`

## 1. Physical Duplicate Files

Byte-identical copies (content hash evidence). Keep one canonical copy.

1. Finding #126 - `00 Agent Inbox`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset '1.3. Cert_LeeBoonSeng.png' has 2 byte-identical copies (4.8 MB each): `00 Agent Inbox/Demo Data/Pass 2 Data/1. Structured Training/1.3. Cert_LeeBoonSeng.png`, `00 Agent Inbox/Gemini_Generated_Image_d7xd09d7xd09d7xd.png`. Keep one canonical copy and remove or link the rest.
2. Finding #127 - `00 Agent Inbox/Document Classification`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'TDD TSA Admin Portal Mockup v1.0 (18 Dec 2025).pptx' has 3 byte-identical copies (4.5 MB each): `00 Agent Inbox/Document Classification/TDD TSA Admin Portal Mockup v1.0 (18 Dec 2025).pptx`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/TDD TSA Admin Portal Mockup v1.0 (18 Dec 2025).pptx`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/TDD TSA Admin Portal Mockup v1.0 (18 Dec 2025).pptx`. Keep one canonical copy and remove or link the rest.
3. Finding #133 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 2 (SUCCESS)`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'Upload_Doc_PassResult.zip' has 2 byte-identical copies (1.6 MB each): `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 2 (SUCCESS)/Upload_Doc_PassResult.zip`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult.zip`. Keep one canonical copy and remove or link the rest.
4. Finding #132 - `01 Project/2026/03_HongLeong/A.2. Proposal/A.2.4. Presentation Slide`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'Proposed POC approach D2701 T1805.pptx' has 2 byte-identical copies (2.2 MB each): `01 Project/2026/03_HongLeong/A.2. Proposal/A.2.4. Presentation Slide/Proposed POC approach D2701 T1805.pptx`, `01 Project/2026/03_HongLeong/A.2. Proposal/A.2.5. Proposal/Proposed POC approach D2701 T1805.pptx`. Keep one canonical copy and remove or link the rest.
5. Finding #134 - `01 Project/2026/03_HongLeong/A.2. Proposal/A.3. DEMO`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'EMB_Business_Loan_Application_Form_Aug_2025.pdf' has 3 byte-identical copies (1.4 MB each): `01 Project/2026/03_HongLeong/A.2. Proposal/A.3. DEMO/EMB_Business_Loan_Application_Form_Aug_2025.pdf`, `01 Project/2026/03_HongLeong/A.2. Proposal/A.3. DEMO/Resources/BAD/EMB_Business_Loan_Application_Form_Aug_2025.pdf`, `01 Project/2026/03_HongLeong/A.2. Proposal/A.3. DEMO/Resources/GOOD/EMB_Business_Loan_Application_Form_Aug_2025.pdf`. Keep one canonical copy and remove or link the rest.
6. Finding #131 - `01 Project/2026/06_MusimMas/A.1. RFI_RFP_RFQ/B.1.1. Introduction_Deck`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset '30Jan26_GeniePresentation[External].pdf' has 2 byte-identical copies (2.2 MB each): `01 Project/2026/06_MusimMas/A.1. RFI_RFP_RFQ/B.1.1. Introduction_Deck/30Jan26_GeniePresentation[External].pdf`, `01 Project/2026/06_MusimMas/A.2. Proposal/30Jan26_GeniePresentation[External].pdf`. Keep one canonical copy and remove or link the rest.
7. Finding #128 - `01 Project/2026/11_Thailand - True Telecom/A.2. Proposal/A.2.3. Timeline`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset '06Oct25_FDE_Overviews_[Internal].pptx' has 2 byte-identical copies (3.7 MB each): `01 Project/2026/11_Thailand - True Telecom/A.2. Proposal/A.2.3. Timeline/06Oct25_FDE_Overviews_[Internal].pptx`, `04 Resources/04 Delivery/05 FDE/06Oct25_FDE_Overviews_[Internal].pptx`. Keep one canonical copy and remove or link the rest.
8. Finding #123 - `01 Project/2026/12_TTSH - Eye Clinic/A.1. RFI_RFP_RFQ/A.1.2. Requirements`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'HC3 MCP User Journey Explanation GenAI_KL (1).pptx' has 2 byte-identical copies (8.0 MB each): `01 Project/2026/12_TTSH - Eye Clinic/A.1. RFI_RFP_RFQ/A.1.2. Requirements/HC3 MCP User Journey Explanation GenAI_KL (1).pptx`, `01 Project/2026/16_TTSH-HC3/A. Presales Activity/03. Presentation Slide/HC3 MCP User Journey Explanation GenAI_KL.pptx`. Keep one canonical copy and remove or link the rest.
9. Finding #125 - `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC4 - PI&PIL/sample PIs`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'SIN02147P_Fraxiparine and Fraxiparine Forte injection PI_09 Mar 2022_PI.pdf' has 2 byte-identical copies (5.7 MB each): `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC4 - PI&PIL/sample PIs/SIN02147P_Fraxiparine and Fraxiparine Forte injection PI_09 Mar 2022_PI.pdf`, `01 Project/2026/17_HSA_Project/B. Delivery Activity/UC4 - PI&PIL/sample PIs/SIN02147P_Fraxiparine and Fraxiparine Forte injection PI_09 Mar 2022_PI.pdf`. Keep one canonical copy and remove or link the rest.
10. Finding #135 - `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC4 - PI&PIL/sample PIs`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'SIN16684P-PI-01_Maxigra_Film_Coated_Tablet_PI_06_Feb_2023_PI.pdf' has 2 byte-identical copies (1.4 MB each): `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC4 - PI&PIL/sample PIs/SIN16684P-PI-01_Maxigra_Film_Coated_Tablet_PI_06_Feb_2023_PI.pdf`, `01 Project/2026/17_HSA_Project/B. Delivery Activity/UC4 - PI&PIL/sample PIs/SIN16684P-PI-01_Maxigra_Film_Coated_Tablet_PI_06_Feb_2023_PI.pdf`. Keep one canonical copy and remove or link the rest.
11. Finding #130 - `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC4 - PI&PIL/sample PIs`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'SIN14881P-PI-01_Keytruda_PI_Oct_2025_04_Nov_2025_PI.pdf' has 2 byte-identical copies (3.5 MB each): `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC4 - PI&PIL/sample PIs/SIN14881P-PI-01_Keytruda_PI_Oct_2025_04_Nov_2025_PI.pdf`, `01 Project/2026/17_HSA_Project/B. Delivery Activity/UC4 - PI&PIL/sample PIs/SIN14881P-PI-01_Keytruda_PI_Oct_2025_04_Nov_2025_PI.pdf`. Keep one canonical copy and remove or link the rest.
12. Finding #129 - `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC4 - PI&PIL/sample PIs`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'SIN14394P-PI-01_A-Sildenafil_PI_22_Aug_2025_PI.pdf' has 2 byte-identical copies (3.6 MB each): `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC4 - PI&PIL/sample PIs/SIN14394P-PI-01_A-Sildenafil_PI_22_Aug_2025_PI.pdf`, `01 Project/2026/17_HSA_Project/B. Delivery Activity/UC4 - PI&PIL/sample PIs/SIN14394P-PI-01_A-Sildenafil_PI_22_Aug_2025_PI.pdf`. Keep one canonical copy and remove or link the rest.
13. Finding #122 - `03 Product/05 Enablement/02 Product Sharing/Genie_NurseScheduling`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'Nurse Scheduling Demo.mov' has 2 byte-identical copies (385.2 MB each): `03 Product/05 Enablement/02 Product Sharing/Genie_NurseScheduling/Nurse Scheduling Demo.mov`, `04 Resources/03 Presales/02 Demo/AI_NurseSchedulingDemo/V3_Nurse Scheduling Demo.mov`. Keep one canonical copy and remove or link the rest.
14. Finding #124 - `04 Resources/03 Presales/02 Demo/AI_CreditRisk_Agent/LoanApplicationAgent_V2`
   - Issue: `knowledge_duplication`
   - Severity: `medium`
   - Confidence: 95%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Asset 'WhatsApp Video 2026-04-10 at 11.09.58.mp4' has 2 byte-identical copies (6.2 MB each): `04 Resources/03 Presales/02 Demo/AI_CreditRisk_Agent/LoanApplicationAgent_V2/Resources/WhatsApp Video 2026-04-10 at 11.09.58.mp4`, `04 Resources/03 Presales/02 Demo/AI_CreditRisk_Agent/LoanApplicationAgent_V2/WhatsApp Video 2026-04-10 at 11.09.58.mp4`. Keep one canonical copy and remove or link the rest.

## 2. Semantic Duplicate Files

Near-identical content by embedding similarity (era_indexer bridge); edited copies and re-saved versions.

1. Finding #142 - `00 Agent Inbox`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'Summary for Salution AI_21Jul26.docx' and 'Summary for Salution AI_21Jul26.docx' are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `00 Agent Inbox/Summary for Salution AI_21Jul26.docx`, `01 Project/2026/17_HSA_Project/A. Presales Activity/09. Sample Data/UC3 - MAST/Summary for Salution AI_21Jul26.docx`. Keep one canonical version or document why each copy exists.
2. Finding #139 - `00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Doc_PassResult`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 7 near-identical files (2.3. OJT_Chen_Mei_Ling.docx, 2.4. OJT_Chen_Mei_Ling.docx) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Doc_PassResult/2.4. OJT_Chen_Mei_Ling.docx`, `00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Docu_FailedResult/2.3. OJT_Chen_Mei_Ling.docx`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/2.3. OJT_Chen_Mei_Ling.docx`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/2.4. OJT_Chen_Mei_Ling.docx`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Document_Set_RUN1_FailedResult/2.3. OJT_Chen_Mei_Ling.docx`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/V2_Upload_Doc_PassResult 2/2.4. OJT_Chen_Mei_Ling.docx`. Keep one canonical version or document why each copy exists.
3. Finding #168 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/B.1. Alignment`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'V2_IBF_Alignment.pptx' and 'V2_IBF_Alignment.pptx' are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/B.1. Alignment/V2_IBF_Alignment.pptx`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC1 - Valudation Checklist/Discussion/V2_IBF_Alignment.pptx`. Keep one canonical version or document why each copy exists.
4. Finding #140 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 9 near-identical files (Payslip_Muhammad_Faris_Dec2025.pdf, Payslip_Muhammad_Faris_Nov2025.pdf, Payslip_Muhammad_Faris_Oct2025.pdf) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Oct2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Dec2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Nov2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
5. Finding #148 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 6 near-identical files (Payslip_Rajesh_Subramaniam_Dec2025.pdf, Payslip_Rajesh_Subramaniam_Nov2025.pdf) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Rajesh_Subramaniam_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Rajesh_Subramaniam_Nov2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Rajesh_Subramaniam_Dec2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Rajesh_Subramaniam_Nov2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/4. Payslips/Payslip_Rajesh_Subramaniam_Dec2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/4. Payslips/Payslip_Rajesh_Subramaniam_Nov2025.pdf`. Keep one canonical version or document why each copy exists.
6. Finding #138 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 9 near-identical files (4.2.3. Payslip_Muhammad_Faris_Oct2025.pdf, 4.3.1. Payslip_Muhammad_Faris_Dec2025.pdf, 4.3.2. Payslip_Muhammad_Faris_Nov2025.pdf, 4.5. Payslip_Muhammad_Faris_Dec2025.pdf...) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.2.3. Payslip_Muhammad_Faris_Oct2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.3.1. Payslip_Muhammad_Faris_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.3.2. Payslip_Muhammad_Faris_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.5. Payslip_Muhammad_Faris_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.5. Payslip_Muhammad_Faris_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.5. Payslip_Muhammad_Faris_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
7. Finding #155 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 7 near-identical files (4.2. Payslip_Lim_Hui_Shan_Dec2025.pdf, 4.2. Payslip_Lim_Hui_Shan_Nov2025.pdf, 4.2. Payslip_Lim_Hui_Shan_Oct2025.pdf, 4.2.1. Payslip_Lim_Hui_Shan_Dec2025.pdf...) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.2.1. Payslip_Lim_Hui_Shan_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.2.2. Payslip_Lim_Hui_Shan_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.2. Payslip_Lim_Hui_Shan_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.2. Payslip_Lim_Hui_Shan_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.2. Payslip_Lim_Hui_Shan_Oct2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Document_Set_RUN1_FailedResult/4.2.1. Payslip_Lim_Hui_Shan_Dec2025.pdf`. Keep one canonical version or document why each copy exists.
8. Finding #153 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 4 near-identical files (4.1.2. Payslip_Chen_Mei_Ling_Nov2025.pdf, 4.4. Payslip_Chen_Mei_Ling_Dec2025.pdf, 4.4. Payslip_Chen_Mei_Ling_Nov2025.pdf) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.1.2. Payslip_Chen_Mei_Ling_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.4. Payslip_Chen_Mei_Ling_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.4. Payslip_Chen_Mei_Ling_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Document_Set_RUN1_FailedResult/4.1.2. Payslip_Chen_Mei_Ling_Nov2025.pdf`. Keep one canonical version or document why each copy exists.
9. Finding #152 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 4 near-identical files (4.4.1. Payslip_Rajesh_Subramaniam_Dec2025.pdf, 4.4.2. Payslip_Rajesh_Subramaniam_Nov2025.pdf) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.4.1. Payslip_Rajesh_Subramaniam_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.4.2. Payslip_Rajesh_Subramaniam_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Document_Set_RUN1_FailedResult/4.4.1. Payslip_Rajesh_Subramaniam_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Document_Set_RUN1_FailedResult/4.4.2. Payslip_Rajesh_Subramaniam_Nov2025.pdf`. Keep one canonical version or document why each copy exists.
10. Finding #143 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 9 near-identical files (4.1. Payslip_Tan_Wei_Ming_Dec2025.pdf, 4.1. Payslip_Tan_Wei_Ming_Nov2025.pdf, 4.1. Payslip_Tan_Wei_Ming_Oct2025.pdf, 4.5.1. Payslip_Tan_Wei_Ming_Dec2025.pdf...) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.5.1. Payslip_Tan_Wei_Ming_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.5.2. Payslip_Tan_Wei_Ming_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/RUN 1 (Failed with Error)/Upload_Document_Set_RUN1_FailedResult/4.5.3. Payslip_Tan_Wei_Ming_Oct2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.1. Payslip_Tan_Wei_Ming_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.1. Payslip_Tan_Wei_Ming_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.1. Payslip_Tan_Wei_Ming_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
11. Finding #162 - `01 Project/2026/01_IBF/3 GenAI_Trends_Sharing/A.2. Proposal/A.2.4. Presentation Slide/V5 - Resources`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'V3.1 - IBF - GenAI Trends EC D1502 T1017.pdf' and 'V5.1 - IBF - GenAI Trends EC D1502 T1017.pdf' are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/01_IBF/3 GenAI_Trends_Sharing/A.2. Proposal/A.2.4. Presentation Slide/V5 - Resources/V5.1 - IBF - GenAI Trends EC D1502 T1017.pdf`, `01 Project/2026/01_IBF/5 Strategy Forward/V3.1 - IBF - GenAI Trends EC D1502 T1017.pdf`. Keep one canonical version or document why each copy exists.
12. Finding #151 - `01 Project/2026/18_VanguardHealth/A.3. Workshop`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'V5_Genie_Studio_Workshop.pptx' and 'V5_Genie_Studio_Workshop.pptx' are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/18_VanguardHealth/A.3. Workshop/V5_Genie_Studio_Workshop.pptx`, `03 Product/05 Enablement/01 Workshop/Basic/V5_Genie_Studio_Workshop.pptx`. Keep one canonical version or document why each copy exists.
13. Finding #167 - `01 Project/2026/20_TemasekPoly_SmartContract/A. Presales Activity/09. Sample Data/Testing_Set (for ST)`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: '8. Two-Ways - MPT - Original.docx' and '8. Two-Ways - MPT - Original_reviewed.docx' are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `01 Project/2026/20_TemasekPoly_SmartContract/A. Presales Activity/09. Sample Data/Testing_Set (for ST)/8. Two-Ways - MPT - Original.docx`, `01 Project/2026/20_TemasekPoly_SmartContract/A. Presales Activity/09. Sample Data/marked_up/8. Two-Ways - MPT - Original_reviewed.docx`. Keep one canonical version or document why each copy exists.
14. Finding #149 - `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 6 near-identical files (Payslip_Tan_Wei_Ming_Dec2025.pdf, Payslip_Tan_Wei_Ming_Nov2025.pdf, Payslip_Tan_Wei_Ming_Oct2025.pdf) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Dec2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Nov2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Oct2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/4. Payslips/Payslip_Tan_Wei_Ming_Dec2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/4. Payslips/Payslip_Tan_Wei_Ming_Nov2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/4. Payslips/Payslip_Tan_Wei_Ming_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
15. Finding #169 - `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 4 near-identical files (Payslip_Chen_Mei_Ling_Dec2025.pdf, Payslip_Chen_Mei_Ling_Nov2025.pdf) are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Chen_Mei_Ling_Dec2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Chen_Mei_Ling_Nov2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/4. Payslips/Payslip_Chen_Mei_Ling_Dec2025.pdf`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/4. Payslips/Payslip_Chen_Mei_Ling_Nov2025.pdf`. Keep one canonical version or document why each copy exists.
16. Finding #163 - `02 Ops/04. Events/2026_09_Sept_GTOGranite`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'V1_27Sept26_GeniePresentationDeck.pptx' and 'V1_29Sept26_GeniePresentationDeck.pptx' are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `02 Ops/04. Events/2026_09_Sept_GTOGranite/V1_29Sept26_GeniePresentationDeck.pptx`, `02 Ops/04. Events/2026_11_Nov_Chairman_Presentation/V1_27Sept26_GeniePresentationDeck.pptx`. Keep one canonical version or document why each copy exists.
17. Finding #154 - `03 Product/04 Engineering/02 Sprint Development/2025_12_Dec`
   - Issue: `semantic_duplication`
   - Severity: `medium`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: '19Dec_Product-Sprint_5_Review[Internal].pptx' and '19Dec_Product-Sprint_5_Review[Internal].pptx' are 100% semantically similar across different folders, creating duplicate maintenance effort. Files: `03 Product/04 Engineering/02 Sprint Development/2025_12_Dec/19Dec_Product-Sprint_5_Review[Internal].pptx`, `03 Product/04 Engineering/02 Sprint Development/2026_01_Jan/19Dec_Product-Sprint_5_Review[Internal].pptx`. Keep one canonical version or document why each copy exists.
18. Finding #147 - `00 Agent Inbox/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 3 near-identical files (Payslip_Tan_Wei_Ming_Dec2025.pdf, Payslip_Tan_Wei_Ming_Nov2025.pdf, Payslip_Tan_Wei_Ming_Oct2025.pdf) are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Dec2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Nov2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
19. Finding #146 - `00 Agent Inbox/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 3 near-identical files (Payslip_Rajesh_Subramaniam_Dec2025.pdf, Payslip_Rajesh_Subramaniam_Nov2025.pdf, Payslip_Rajesh_Subramaniam_Oct2025.pdf) are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Rajesh_Subramaniam_Dec2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Rajesh_Subramaniam_Nov2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Rajesh_Subramaniam_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
20. Finding #141 - `00 Agent Inbox/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 3 near-identical files (Payslip_Muhammad_Faris_Dec2025.pdf, Payslip_Muhammad_Faris_Nov2025.pdf, Payslip_Muhammad_Faris_Oct2025.pdf) are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Dec2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Nov2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Muhammad_Faris_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
21. Finding #166 - `00 Agent Inbox/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 3 near-identical files (Payslip_Lim_Hui_Shan_Dec2025.pdf, Payslip_Lim_Hui_Shan_Nov2025.pdf, Payslip_Lim_Hui_Shan_Oct2025.pdf) are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Lim_Hui_Shan_Dec2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Lim_Hui_Shan_Nov2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Lim_Hui_Shan_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
22. Finding #156 - `00 Agent Inbox/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'Payslip_Chen_Mei_Ling_Dec2025.pdf' and 'Payslip_Chen_Mei_Ling_Nov2025.pdf' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Chen_Mei_Ling_Dec2025.pdf`, `00 Agent Inbox/Demo Data/4. Payslips/Payslip_Chen_Mei_Ling_Nov2025.pdf`. Keep one canonical version or document why each copy exists.
23. Finding #165 - `00 Agent Inbox/Demo Data/Pass 2 Data/4. Payslip`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 3 near-identical files (Payslip_Priya_Nair_Dec2025.pdf, Payslip_Priya_Nair_Nov2025.pdf, Payslip_Priya_Nair_Oct2025.pdf) are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `00 Agent Inbox/Demo Data/Pass 2 Data/4. Payslip/Payslip_Priya_Nair_Dec2025.pdf`, `00 Agent Inbox/Demo Data/Pass 2 Data/4. Payslip/Payslip_Priya_Nair_Nov2025.pdf`, `00 Agent Inbox/Demo Data/Pass 2 Data/4. Payslip/Payslip_Priya_Nair_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
24. Finding #170 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'Payslip_Lim_Hui_Shan_Dec2025.pdf' and 'Payslip_Lim_Hui_Shan_Nov2025.pdf' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Lim_Hui_Shan_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Lim_Hui_Shan_Nov2025.pdf`. Keep one canonical version or document why each copy exists.
25. Finding #145 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 3 near-identical files (Payslip_Tan_Wei_Ming_Dec2025.pdf, Payslip_Tan_Wei_Ming_Nov2025.pdf, Payslip_Tan_Wei_Ming_Oct2025.pdf) are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Tan_Wei_Ming_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
26. Finding #161 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'Payslip_Chen_Mei_Ling_Dec2025.pdf' and 'Payslip_Chen_Mei_Ling_Nov2025.pdf' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Chen_Mei_Ling_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips/Payslip_Chen_Mei_Ling_Nov2025.pdf`. Keep one canonical version or document why each copy exists.
27. Finding #144 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 3 near-identical files (4.3.  Payslip_Rajesh_Subramaniam_Dec2025.pdf, 4.3.  Payslip_Rajesh_Subramaniam_Nov2025.pdf, 4.3.  Payslip_Rajesh_Subramaniam_Oct2025.pdf) are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.3.  Payslip_Rajesh_Subramaniam_Dec2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.3.  Payslip_Rajesh_Subramaniam_Nov2025.pdf`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/Upload_Doc_PassResult/4.3.  Payslip_Rajesh_Subramaniam_Oct2025.pdf`. Keep one canonical version or document why each copy exists.
28. Finding #160 - `01 Project/2026/17_HSA_Project/Phase 1/Sharing`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'HSA_AI_Platform_Running_Document_10_Sep_Eclypse_v7.pptx' and 'HSA_AI_Platform_Running_Document_3_Sep_Eclypse_v6.pptx' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `01 Project/2026/17_HSA_Project/Phase 1/Sharing/HSA_AI_Platform_Running_Document_10_Sep_Eclypse_v7.pptx`, `01 Project/2026/17_HSA_Project/Phase 1/Sharing/HSA_AI_Platform_Running_Document_3_Sep_Eclypse_v6.pptx`. Keep one canonical version or document why each copy exists.
29. Finding #137 - `02 Ops/01. Daily_Todo/2025_10_Oct`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: '07Oct2025.md' and '09Oct2025.md' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `02 Ops/01. Daily_Todo/2025_10_Oct/07Oct2025.md`, `02 Ops/01. Daily_Todo/2025_10_Oct/09Oct2025.md`. Keep one canonical version or document why each copy exists.
30. Finding #150 - `02 Ops/01. Daily_Todo/2026_01_Jan`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: '02Jan2026.md' and '06Jan2026.md' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `02 Ops/01. Daily_Todo/2026_01_Jan/02Jan2026.md`, `02 Ops/01. Daily_Todo/2026_01_Jan/06Jan2026.md`. Keep one canonical version or document why each copy exists.
31. Finding #164 - `02 Ops/03. Internal_Presentation/2025_09_Sept`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: '04Nov29_ForwardDeplyedEngineer[Internal]_v2.pptx' and '25Sep29_ForwardDeplyedEngineer[Internal].pptx' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `02 Ops/03. Internal_Presentation/2025_09_Sept/04Nov29_ForwardDeplyedEngineer[Internal]_v2.pptx`, `02 Ops/03. Internal_Presentation/2025_09_Sept/25Sep29_ForwardDeplyedEngineer[Internal].pptx`. Keep one canonical version or document why each copy exists.
32. Finding #158 - `02 Ops/04. Events/2025_12_Dec_SFF`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: '06Nov26_GeniePresentation[External].pptx' and '26Nov26_GeniePresentation_SFF[External].pptx' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `02 Ops/04. Events/2025_12_Dec_SFF/06Nov26_GeniePresentation[External].pptx`, `02 Ops/04. Events/2025_12_Dec_SFF/26Nov26_GeniePresentation_SFF[External].pptx`. Keep one canonical version or document why each copy exists.
33. Finding #136 - `03 Product/04 Engineering/02 Sprint Development/2025_11_Nov`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: '20Nov_Product-Sprint_4_Review[Internal]-20251121154532.pdf' and '20Nov_Product-Sprint_4_Review[Internal]-20251121154555.pdf' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `03 Product/04 Engineering/02 Sprint Development/2025_11_Nov/20Nov_Product-Sprint_4_Review[Internal]-20251121154532.pdf`, `03 Product/04 Engineering/02 Sprint Development/2025_11_Nov/20Nov_Product-Sprint_4_Review[Internal]-20251121154555.pdf`. Keep one canonical version or document why each copy exists.
34. Finding #157 - `03 Product/05 Enablement/06 UseCase Architecture Master Deck`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: '16Jun26_Full_Architecture&Demo_V3.pptx' and '27Sept26_Full_Architecture&Demo_V3.pptx' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `03 Product/05 Enablement/06 UseCase Architecture Master Deck/16Jun26_Full_Architecture&Demo_V3.pptx`, `03 Product/05 Enablement/06 UseCase Architecture Master Deck/27Sept26_Full_Architecture&Demo_V3.pptx`. Keep one canonical version or document why each copy exists.
35. Finding #159 - `05 Admin/02 People & HR/03 Team Handover/Albert - Handover`
   - Issue: `semantic_duplication`
   - Severity: `low`
   - Confidence: 99%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: 'Genie Studio v1.4.1 (1).pptx' and 'Genie Studio v1.4.2 (1).pptx' are 100% semantically similar within one initiative (likely working drafts/exports - tidy up if you no longer need every copy). Files: `05 Admin/02 People & HR/03 Team Handover/Albert - Handover/Genie Studio v1.4.1 (1).pptx`, `05 Admin/02 People & HR/03 Team Handover/Albert - Handover/Genie Studio v1.4.2 (1).pptx`. Keep one canonical version or document why each copy exists.

## 3. Reusable Asset Advisory (informational)

Advisory only. The auditor never recommends moving files out of a project: project copies preserve archive self-containment. Centralization is suggested only when an asset crosses multiple customers and shows active maintenance, and even then the action is to COPY a canonical version into 04 Resources, not relocate.

### Most Reused Assets

| Score | Asset | Type | Copies | Projects | Customers | Canonical Location |
| ---: | --- | --- | ---: | ---: | ---: | --- |
| 67 | V5_Genie_Studio_Workshop.pptx | presentation | 4 | 3 | 2 | `01 Project/2026/18_VanguardHealth/A.3. Workshop/V5_Genie_Studio_Workshop.pptx` (advisory: consider COPYING to 04 Resources) |
| 54 | CPF_ROP_Meridian_DEC_2025.png | media | 11 | 1 | 1 | `00 Agent Inbox/Demo Data/5. CPF/CPF_ROP_Meridian_DEC_2025.png` (project-local, keep in place) |
| 54 | CPF_ROP_Meridian_NOV_2025.png | media | 11 | 1 | 1 | `00 Agent Inbox/Demo Data/5. CPF/CPF_ROP_Meridian_NOV_2025.png` (project-local, keep in place) |
| 54 | CPF_ROP_Meridian_OCT_2025.png | media | 11 | 1 | 1 | `00 Agent Inbox/Demo Data/5. CPF/CPF_ROP_Meridian_OCT_2025.png` (project-local, keep in place) |
| 54 | PMP® - Project Management Professional® Exam Preparatory Course.pdf | document | 11 | 1 | 1 | `00 Agent Inbox/Demo Data/1. Structured Training/PMP® - Project Management Professional® Exam Preparatory Course.pdf` (project-local, keep in place) |
| 54 | 1.2. Cert_Lim_Hui_Shan.jpg | media | 10 | 1 | 1 | `00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Doc_PassResult/1.2. Cert_Lim_Hui_Shan.jpg` (project-local, keep in place) |
| 54 | 1.3. Cert_Rajesh_Subramaniam.jpg | media | 10 | 1 | 1 | `00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Doc_PassResult/1.3. Cert_Rajesh_Subramaniam.jpg` (project-local, keep in place) |
| 54 | 1.5. Cert_Muhammad_Faris.jpg | media | 10 | 1 | 1 | `00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Doc_PassResult/1.5. Cert_Muhammad_Faris.jpg` (project-local, keep in place) |
| 54 | 2.2. OJT_Lim_Hui_Shan.docx | document | 10 | 1 | 1 | `00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Doc_PassResult/2.2. OJT_Lim_Hui_Shan.docx` (project-local, keep in place) |
| 54 | Redesignation_Chen_Mei_Ling.pdf | document | 9 | 1 | 1 | `00 Agent Inbox/Demo Data/3. Redesignation Letters/Redesignation_Chen_Mei_Ling.pdf` (project-local, keep in place) |


1. Finding #171 - `01 Project/2026/06_MusimMas/A.2. Proposal/B.2.1. Studio Training`
   - Issue: `reusable_asset`
   - Severity: `low`
   - Confidence: 60%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Advisory: asset 'V5_Genie_Studio_Workshop.pptx' appears across 2 customers with 4 diverging copies, so it may be worth centralizing IF it requires ongoing maintenance and a shared canonical version would reduce future work. The copies inside project folders preserve archive self-containment - do NOT move them. If you promote, COPY one canonical version into 04 Resources and keep the project copies. Copies: `01 Project/2026/06_MusimMas/A.2. Proposal/B.2.1. Studio Training/V5_Genie_Studio_Workshop.pptx`, `01 Project/2026/18_VanguardHealth/A.3. Workshop/V5_Genie_Studio_Workshop.pptx`, `01 Project/2026/18_VanguardHealth/A.3.B. Workshop 2/V5_Genie_Studio_Workshop.pptx`, `03 Product/05 Enablement/01 Workshop/Basic/V5_Genie_Studio_Workshop.pptx`.

## 4. Resource Leakage

No findings in this category.

## 5. Architecture Review

Structural decisions, not violations: the same topic lives under multiple roots. Decide a canonical home or document the split.

1. Finding #108 - `00 Agent Inbox/Demo Data`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'demo data' lives under 00 Agent Inbox and 01 Project and 02 Ops (`00 Agent Inbox/Demo Data`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
2. Finding #118 - `00 Agent Inbox/Demo Data/1. Structured Training`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'structured training' lives under 00 Agent Inbox and 01 Project and 02 Ops (`00 Agent Inbox/Demo Data/1. Structured Training`, `00 Agent Inbox/Demo Data/Pass 2 Data/1. Structured Training`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/1. Structured Training`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/1. Structured Training`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/1. Structured Training`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
3. Finding #110 - `00 Agent Inbox/Demo Data/2. OJT`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'ojt' lives under 00 Agent Inbox and 01 Project and 02 Ops (`00 Agent Inbox/Demo Data/2. OJT`, `00 Agent Inbox/Demo Data/Pass 2 Data/2. OJT`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/2. OJT`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/2. OJT`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/2. OJT`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
4. Finding #114 - `00 Agent Inbox/Demo Data/3. Redesignation Letters`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'redesignation letters' lives under 00 Agent Inbox and 01 Project and 02 Ops (`00 Agent Inbox/Demo Data/3. Redesignation Letters`, `00 Agent Inbox/Demo Data/Pass 2 Data/3. Redesignation Letters`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/3. Redesignation Letters`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/3. Redesignation Letters`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/3. Redesignation Letters`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
5. Finding #112 - `00 Agent Inbox/Demo Data/4. Payslips`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'payslips' lives under 00 Agent Inbox and 01 Project and 02 Ops (`00 Agent Inbox/Demo Data/4. Payslips`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/4. Payslips`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/4. Payslips`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
6. Finding #107 - `00 Agent Inbox/Demo Data/5. CPF`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'cpf' lives under 00 Agent Inbox and 01 Project and 02 Ops (`00 Agent Inbox/Demo Data/5. CPF`, `00 Agent Inbox/Demo Data/Pass 2 Data/5. CPF`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Demo Data/5. CPF`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Demo Data/5. CPF`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Resources/(Failed) Sample Files/5. CPF`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
7. Finding #111 - `00 Agent Inbox/Demo Data/Pass 2 Data/4. Payslip`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'payslip' lives under 00 Agent Inbox and 05 Admin (`00 Agent Inbox/Demo Data/Pass 2 Data/4. Payslip`, `05 Admin/02 People & HR/02 HR Onboarding/Required Documents/PaySlip`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
8. Finding #113 - `00 Agent Inbox/Document Classification/Public Portal Mockups`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'public portal mockups' lives under 00 Agent Inbox and 01 Project and 02 Ops (`00 Agent Inbox/Document Classification/Public Portal Mockups`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
9. Finding #119 - `00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Docu_FailedResult`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'v2 upload docu failedresult' lives under 00 Agent Inbox and 01 Project (`00 Agent Inbox/IBF CCP - Demo Data V2/V2_Upload_Docu_FailedResult`, `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/02 RequirementGathering/V2_Upload_Docu_FailedResult`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
10. Finding #115 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step1-upload_document`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'step1-upload document' lives under 01 Project and 02 Ops (`01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step1-upload_document`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step1-upload_document`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
11. Finding #116 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step2-check_completeness`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'step2-check completeness' lives under 01 Project and 02 Ops (`01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step2-check_completeness`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step2-check_completeness`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
12. Finding #117 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step3-review_claim_form`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'step3-review claim form' lives under 01 Project and 02 Ops (`01 Project/2026/01_IBF/2 CPX - AI Use Case/CCP - AI Document Intelligence/01 Demo_ProjectMeeting/AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step3-review_claim_form`, `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/Public Portal Mockups/Step3-review_claim_form`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
13. Finding #109 - `01 Project/2026/01_IBF/7 Compliances Audit Check/A. Presales Activity/06. Effort Estimation`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'effort estimation' lives under 01 Project and 04 Resources (`01 Project/2026/01_IBF/7 Compliances Audit Check/A. Presales Activity/06. Effort Estimation`, `01 Project/2026/16_TTSH-HC3/A. Presales Activity/06. Effort Estimation`, `01 Project/2026/20_TemasekPoly_SmartContract/A. Presales Activity/06. Effort Estimation`, `01 Project/2026/24_IHH_DigitalConcierge/A. Presales Activity/06. Effort Estimation`, `04 Resources/03 Presales/08 Effort Estimation`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
14. Finding #120 - `01 Project/2026/19_TaiyoYuden/A. Presales Activity/99. Workshop`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic 'workshop' lives under 01 Project and 03 Product (`01 Project/2026/19_TaiyoYuden/A. Presales Activity/99. Workshop`, `03 Product/05 Enablement/01 Workshop`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
15. Finding #99 - `02 Ops/01. Daily_Todo/2025_10_Oct`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic '2025 10 oct' lives under 02 Ops and 03 Product (`02 Ops/01. Daily_Todo/2025_10_Oct`, `02 Ops/02. Internal_Meeting_Notes/2025_10_Oct`, `02 Ops/03. Internal_Presentation/2025_10_Oct`, `03 Product/04 Engineering/02 Sprint Development/2025_10_Oct`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
16. Finding #100 - `02 Ops/01. Daily_Todo/2025_11_Nov`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic '2025 11 nov' lives under 02 Ops and 03 Product (`02 Ops/01. Daily_Todo/2025_11_Nov`, `02 Ops/02. Internal_Meeting_Notes/2025_11_Nov`, `02 Ops/03. Internal_Presentation/2025_11_Nov`, `03 Product/04 Engineering/02 Sprint Development/2025_11_Nov`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
17. Finding #101 - `02 Ops/01. Daily_Todo/2025_12_Dec`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic '2025 12 dec' lives under 02 Ops and 03 Product (`02 Ops/01. Daily_Todo/2025_12_Dec`, `02 Ops/03. Internal_Presentation/2025_12_Dec`, `03 Product/04 Engineering/02 Sprint Development/2025_12_Dec`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
18. Finding #102 - `02 Ops/01. Daily_Todo/2026_01_Jan`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic '2026 01 jan' lives under 02 Ops and 03 Product (`02 Ops/01. Daily_Todo/2026_01_Jan`, `02 Ops/02. Internal_Meeting_Notes/2026_01_Jan`, `02 Ops/03. Internal_Presentation/2026_01_Jan`, `03 Product/04 Engineering/02 Sprint Development/2026_01_Jan`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
19. Finding #103 - `02 Ops/01. Daily_Todo/2026_02_Feb`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic '2026 02 feb' lives under 02 Ops and 03 Product (`02 Ops/01. Daily_Todo/2026_02_Feb`, `02 Ops/02. Internal_Meeting_Notes/2026_02_Feb`, `03 Product/04 Engineering/02 Sprint Development/2026_02_Feb`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
20. Finding #105 - `02 Ops/01. Daily_Todo/2026_04_Apr`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic '2026 04 apr' lives under 02 Ops and 03 Product (`02 Ops/01. Daily_Todo/2026_04_Apr`, `02 Ops/03. Internal_Presentation/2026_04_Apr`, `03 Product/04 Engineering/02 Sprint Development/2026_04_Apr`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
21. Finding #106 - `02 Ops/01. Daily_Todo/2026_05_May`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic '2026 05 may' lives under 02 Ops and 03 Product (`02 Ops/01. Daily_Todo/2026_05_May`, `02 Ops/02. Internal_Meeting_Notes/2026_05_May`, `03 Product/04 Engineering/02 Sprint Development/2026_05_May`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.
22. Finding #104 - `02 Ops/03. Internal_Presentation/2026_03_Mar`
   - Issue: `architecture_review`
   - Severity: `low`
   - Confidence: 70%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Topic '2026 03 mar' lives under 02 Ops and 03 Product (`02 Ops/03. Internal_Presentation/2026_03_Mar`, `03 Product/04 Engineering/02 Sprint Development/2026_03_Mar`). Is it an operational function, a reusable knowledge library, or intentionally both? Decide a canonical home or document the split so future retrieval is unambiguous.

## 6. Naming Corrections

1. Finding #75 - `01 Project/2026/01_IBF/1 AI Staff Training/A. PreSales/A.1. RFI.RFP.RFQ`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 85%
   - Suggested action: `standardize`
   - Suggested destination: `A.1. RFI_RFP_RFQ`
   - Reason: Folder name 'A.1. RFI.RFP.RFQ' is an alias spelling of the canonical stage 'A.1. RFI_RFP_RFQ'.
2. Finding #77 - `01 Project/2026/01_IBF/6 Transformation of IBF Programme Accreditation/A.1. RFI.RFP.RFQ`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 85%
   - Suggested action: `standardize`
   - Suggested destination: `A.1. RFI_RFP_RFQ`
   - Reason: Folder name 'A.1. RFI.RFP.RFQ' is an alias spelling of the canonical stage 'A.1. RFI_RFP_RFQ'.
3. Finding #96 - `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC1 - Valudation Checklist`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 85%
   - Suggested action: `rename`
   - Suggested destination: `UC1 - Validation Checklist`
   - Reason: Folder name contains the misspelling 'valudation'; suggested spelling: 'UC1 - Validation Checklist'.
4. Finding #97 - `02 Ops/04. Events/2026_06_Jun_IBF_Innosuite/UC2 - AI-Powered Document Intelligence for CCP Claims/ADDITONAL_DATASET`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 85%
   - Suggested action: `rename`
   - Suggested destination: `Additional_DATASET`
   - Reason: Folder name contains the misspelling 'additonal'; suggested spelling: 'Additional_DATASET'.
5. Finding #72 - `01 Project/2026/01_IBF/1 AI Staff Training/A. PreSales/A.1. RFI.RFP.RFQ`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 76%
   - Suggested action: `standardize`
   - Suggested destination: `A.1. RFI_RFP_RFQ`
   - Reason: Stage folder matches a known alias but differs from the canonical naming standard.
6. Finding #73 - `01 Project/2026/01_IBF/2 CPX - AI Use Case/A.1. RFI_RFP_RFQ/A.1.3. Meeting Notes/Internal_Meeting`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 76%
   - Suggested action: `standardize`
   - Suggested destination: `A.3.2. Internal Discussion`
   - Reason: Stage folder matches a known alias but differs from the canonical naming standard.
7. Finding #70 - `01 Project/2026/01_IBF/5 Strategy Forward/Internal_Meeting`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 76%
   - Suggested action: `standardize`
   - Suggested destination: `A.3.2. Internal Discussion`
   - Reason: Stage folder matches a known alias but differs from the canonical naming standard.
8. Finding #71 - `01 Project/2026/01_IBF/6 Transformation of IBF Programme Accreditation/A.1. RFI.RFP.RFQ`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 76%
   - Suggested action: `standardize`
   - Suggested destination: `A.1. RFI_RFP_RFQ`
   - Reason: Stage folder matches a known alias but differs from the canonical naming standard.
9. Finding #74 - `01 Project/2026/03_HongLeong/A.2. Proposal/HL Bank - POC/SprintReview_1/Internal Meeting`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 76%
   - Suggested action: `standardize`
   - Suggested destination: `A.3.2. Internal Discussion`
   - Reason: Stage folder matches a known alias but differs from the canonical naming standard.
10. Finding #69 - `01 Project/2026/07_MY_MOH/A.1. RFI`
   - Issue: `naming_inconsistency`
   - Severity: `low`
   - Confidence: 76%
   - Suggested action: `standardize`
   - Suggested destination: `A.1. RFI_RFP_RFQ`
   - Reason: Stage folder matches a known alias but differs from the canonical naming standard.

## Template Drift

Validated against each initiative's archetype template (sales opportunities use the A/B/C stage tree; workshops, strategic initiatives, and artifacts are never asked for PreSales).

1. Finding #78 - `01 Project/2026/01_IBF/6 Transformation of IBF Programme Accreditation/A.2. Proposal/A.2.6. ProposalDocument`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 90%
   - Suggested action: `renumber`
   - Suggested destination: `01 Project/2026/01_IBF/6 Transformation of IBF Programme Accreditation/A.2. Proposal/A.2.8. ProposalDocument`
   - Reason: Stage prefix 'A.2.6.' is used by more than one sibling folder; renumbering to 'A.2.8. ProposalDocument' keeps indices unique while core stages keep their canonical numbers.
2. Finding #82 - `01 Project/2026/03_HongLeong/A.2. Proposal/A.2.5. Proposal`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 90%
   - Suggested action: `renumber`
   - Suggested destination: `01 Project/2026/03_HongLeong/A.2. Proposal/A.2.6. Proposal`
   - Reason: Stage prefix 'A.2.5.' is used by more than one sibling folder; renumbering to 'A.2.6. Proposal' keeps indices unique while core stages keep their canonical numbers.
3. Finding #98 - `01 Project/<RENAME_PROJECT>`
   - Issue: `template_drift`
   - Severity: `low`
   - Confidence: 90%
   - Suggested action: `move`
   - Suggested destination: `04 Resources/02 Delivery/00 Templates`
   - Reason: Placeholder scaffold folder sits among real project folders. Either rename it for a real project or relocate the scaffold next to the other templates.
4. Finding #76 - `01 Project/2026/01_IBF/3 GenAI_Trends_Sharing/A.1. RFI_RFP_RFQ/B.1.4. PresentationDeck`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.1.4.' belongs to stage 'B.' but it is nested under stage 'A.1.'.
5. Finding #83 - `01 Project/2026/03_HongLeong/A.2. Proposal/B.1. Resources`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.1.' belongs to stage 'B.' but it is nested under stage 'A.2.'.
6. Finding #84 - `01 Project/2026/03_HongLeong/A.2. Proposal/B.2. POC Resources`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.2.' belongs to stage 'B.' but it is nested under stage 'A.2.'.
7. Finding #85 - `01 Project/2026/06_MusimMas/A.1. RFI_RFP_RFQ/A.1.2. Requirements/B.1.2. RFP Proposal Slides`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.1.2.' belongs to stage 'B.' but it is nested under stage 'A.1.2.'.
8. Finding #86 - `01 Project/2026/06_MusimMas/A.1. RFI_RFP_RFQ/B.1.1. Introduction_Deck`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.1.1.' belongs to stage 'B.' but it is nested under stage 'A.1.'.
9. Finding #87 - `01 Project/2026/06_MusimMas/A.2. Proposal/B.2.1. Studio Training`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.2.1.' belongs to stage 'B.' but it is nested under stage 'A.2.'.
10. Finding #88 - `01 Project/2026/06_MusimMas/A.2. Proposal/B.2.2. CCA Project`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.2.2.' belongs to stage 'B.' but it is nested under stage 'A.2.'.
11. Finding #89 - `01 Project/2026/12_TTSH - Eye Clinic/A.1. RFI_RFP_RFQ/B.1.1 Resources`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.1.1.' belongs to stage 'B.' but it is nested under stage 'A.1.'.
12. Finding #90 - `01 Project/2026/12_TTSH - Eye Clinic/A.1. RFI_RFP_RFQ/C.1.1. Demo`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'C. Post Sales'`
   - Reason: Folder prefix 'C.1.1.' belongs to stage 'C.' but it is nested under stage 'A.1.'.
13. Finding #91 - `01 Project/2026/12_TTSH - Eye Clinic/A.1. RFI_RFP_RFQ/C.1.2. Evaluation Qns`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'C. Post Sales'`
   - Reason: Folder prefix 'C.1.2.' belongs to stage 'C.' but it is nested under stage 'A.1.'.
14. Finding #92 - `01 Project/2026/12_TTSH - Eye Clinic/A.2. Proposal/B.1. Model Analysis`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'B. Delivery'`
   - Reason: Folder prefix 'B.1.' belongs to stage 'B.' but it is nested under stage 'A.2.'.
15. Finding #93 - `01 Project/2026/12_TTSH - Eye Clinic/Z. AI_Notebook/A.2. Proposal`
   - Issue: `template_drift`
   - Severity: `medium`
   - Confidence: 88%
   - Suggested action: `move`
   - Suggested destination: `under 'A. PreSales'`
   - Reason: Folder prefix 'A.2.' belongs to stage 'A.' but it is nested under stage 'Z.'.
16. Finding #95 - `01 Project/2026/19_TaiyoYuden`
   - Issue: `project_completeness`
   - Severity: `medium`
   - Confidence: 85%
   - Suggested action: `review`
   - Suggested destination: `01 Project/2026/19_TaiyoYuden/A.2. Proposal`
   - Reason: Active presales project is missing the core template stage 'A.2. Proposal'.
17. Finding #94 - `01 Project/2026/19_TaiyoYuden`
   - Issue: `project_completeness`
   - Severity: `medium`
   - Confidence: 85%
   - Suggested action: `review`
   - Suggested destination: `01 Project/2026/19_TaiyoYuden/A.1. RFI_RFP_RFQ`
   - Reason: Active presales project is missing the core template stage 'A.1. RFI_RFP_RFQ'.
18. Finding #79 - `01 Project/2026/01_IBF/6 Transformation of IBF Programme Accreditation/A.2. Proposal/A.2.4. Timeline`
   - Issue: `template_drift`
   - Severity: `low`
   - Confidence: 80%
   - Suggested action: `renumber`
   - Suggested destination: `A.2.3. Timeline`
   - Reason: Folder 'A.2.4. Timeline' matches the template stage 'A.2.3. Timeline' but carries index 'A.2.4.' instead of 'A.2.3.'.
19. Finding #80 - `01 Project/2026/01_IBF/6 Transformation of IBF Programme Accreditation/A.2. Proposal/A.2.5. Presentation Slide`
   - Issue: `template_drift`
   - Severity: `low`
   - Confidence: 80%
   - Suggested action: `renumber`
   - Suggested destination: `A.2.4. Presentation Slide`
   - Reason: Folder 'A.2.5. Presentation Slide' matches the template stage 'A.2.4. Presentation Slide' but carries index 'A.2.5.' instead of 'A.2.4.'.
20. Finding #81 - `01 Project/2026/01_IBF/6 Transformation of IBF Programme Accreditation/A.2. Proposal/A.2.6. Contract`
   - Issue: `template_drift`
   - Severity: `low`
   - Confidence: 80%
   - Suggested action: `renumber`
   - Suggested destination: `A.2.5. Contract`
   - Reason: Folder 'A.2.6. Contract' matches the template stage 'A.2.5. Contract' but carries index 'A.2.6.' instead of 'A.2.5.'.

## Registry Enrichment

Registry gaps are maintenance tasks, not architecture issues.

No findings in this category.

## Librarian Training Signals

Findings that improve future placement accuracy. Registering these initiatives (customer + initiative_type + canonical_path) teaches the Placement Engine where new files belong.

1. Finding #121 - `01 Project/2026/08_NUHS/01Oct2025 - NUHS`
   - Issue: `missing_initiative_metadata`
   - Severity: `low`
   - Confidence: 60%
   - Suggested action: `document_decision`
   - Suggested destination: `None`
   - Reason: Initiative '01Oct2025 - NUHS' has no registered archetype (customer / initiative_type / canonical_path). The Librarian cannot confidently place new files for it until this is known. Add it to the project registry to improve placement accuracy.

## Informational: Leads and Unconnected Knowledge

1. Finding #68 - `01 Project/<RENAME_PROJECT>`
   - Issue: `orphaned_knowledge`
   - Severity: `medium`
   - Confidence: 66%
   - Suggested action: `review`
   - Suggested destination: `None`
   - Reason: Folder contains content but is not connected to a known project, customer, product, operation, administration area, or resource category.

## Other Findings

No findings in this category.

## Suppressed Noise Summary

- Folder-name similarity never generates duplication findings; only content evidence (hashes, embeddings) does.
- Numbering prefixes are ordering aids, not identifiers: shared sibling prefixes never generate findings.
- Month/version/Resources/Templates container names and temporal partitions never generate findings.
- Resources/Templates folders inside projects are project self-containment, never leakage findings.
- Asset reuse is advisory only: promotion is suggested solely for multi-customer, actively maintained assets, and never as a move (copy only).
- Empty inbox folders, temporal year folders, code repositories, and pure depth warnings are intentionally suppressed.
- App-settings subtrees in scanner.ignore_subtrees are skipped entirely.
- Previously rejected recommendation patterns are skipped when present in auditor decision history.
