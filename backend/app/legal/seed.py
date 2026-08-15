"""
KAEOS Legal Domain — Database Seed Script
Seeds the Legal tables with realistic corporate agreements, SOX/GDPR regulations,
lawsuits, patents, and DSAR logs.
"""
import asyncio
import uuid
from datetime import date, timedelta

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base

# Models imports
from app.legal.models.core import LegalMatter, LegalTeamMember, MatterStatus, MatterPriority
from app.legal.models.contracts import Contract, ContractClause, ContractTemplate, ContractStatus, ClauseRiskLevel
from app.legal.models.compliance import RegulatoryRequirement, ComplianceObligation, ComplianceAssessment, ObligationStatus
from app.legal.models.litigation import Case, CaseEvent, CourtFiling, CaseStage
from app.legal.models.ip import Patent, Trademark, TradeSecret, IPStatus
from app.legal.models.privacy import DataSubjectRequest, PrivacyImpactAssessment, DataProcessingRecord, DsarType, DsarStatus

TENANT = "tenant_acme"  # demo tenant — matches seed_demo_user and dev-mode tenant

def _id():
    return str(uuid.uuid4())

async def seed():
    # Ensure tables are built
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Legal Team Members
        lawyers = [
            LegalTeamMember(id=_id(), tenant_id=TENANT, name="Sarah Jenkins", role="General Counsel", email="sarah.jenkins@kaeos.io", bar_license_number="CA-99214", is_active=True),
            LegalTeamMember(id=_id(), tenant_id=TENANT, name="David Ross", role="IP Attorney", email="david.ross@kaeos.io", bar_license_number="NY-88712", is_active=True),
            LegalTeamMember(id=_id(), tenant_id=TENANT, name="Elena Rostova", role="Privacy & Compliance Lead", email="elena.rostova@kaeos.io", bar_license_number="MA-44120", is_active=True)
        ]
        for l in lawyers:
            db.add(l)
        await db.flush()

        # 2. General Matters
        matters = [
            LegalMatter(id=_id(), tenant_id=TENANT, title="Acquisition of Orion Tech Corp", description="Due diligence and drafting of definitive merger agreement.", matter_type="M&A", status=MatterStatus.IN_PROGRESS, priority=MatterPriority.HIGH, assigned_attorney_id=lawyers[0].id, external_counsel="Skadden Arps LLP"),
            LegalMatter(id=_id(), tenant_id=TENANT, title="Employee Dispute - Wrongful Termination", description="Disgruntled sales lead claiming unpaid commissions and wrongful dismissal.", matter_type="Employment", status=MatterStatus.NEW, priority=MatterPriority.MEDIUM, assigned_attorney_id=lawyers[0].id),
            LegalMatter(id=_id(), tenant_id=TENANT, title="Trademark Licensing - KAEOS Brand Partners", description="Negotiate co-branding and trademark license terms with a channel reseller.", matter_type="Intellectual Property", status=MatterStatus.RESOLVED, priority=MatterPriority.LOW, assigned_attorney_id=lawyers[1].id, resolution="License executed at standard royalty terms; no exclusivity granted."),
            LegalMatter(id=_id(), tenant_id=TENANT, title="Vendor Data Incident Review", description="Assessing a subprocessor's data handling after a reported access anomaly.", matter_type="Corporate", status=MatterStatus.ON_HOLD, priority=MatterPriority.CRITICAL, assigned_attorney_id=lawyers[2].id, external_counsel="Cooley LLP"),
        ]
        for m in matters:
            db.add(m)
        await db.flush()

        # 3. Contracts
        contracts = [
            Contract(id=_id(), tenant_id=TENANT, title="Enterprise SaaS Agreement - Stark Ind", counterparty="Stark Industries Global", contract_type="MSA", status=ContractStatus.ACTIVE, contract_value=250000.00, effective_date=date.today() - timedelta(days=60), expiry_date=date.today() + timedelta(days=305), auto_renew=True, ai_risk_score=15.0, ai_summary="Standard outbound enterprise SaaS agreement. Governing law set to New York. Includes reciprocal IP protections."),
            Contract(id=_id(), tenant_id=TENANT, title="Strategic Partnership SOW - Wayne Corp", counterparty="Wayne Enterprises Inc", contract_type="SOW", status=ContractStatus.IN_REVIEW, contract_value=120000.00, effective_date=None, expiry_date=None, auto_renew=False),
            Contract(id=_id(), tenant_id=TENANT, title="Mutual NDA - Cyberdyne Systems", counterparty="Cyberdyne Systems Corp", contract_type="NDA", status=ContractStatus.DRAFT, contract_value=None, effective_date=None, expiry_date=None, auto_renew=False),
            Contract(id=_id(), tenant_id=TENANT, title="Cloud Hosting MSA - Globex", counterparty="Globex Corporation", contract_type="MSA", status=ContractStatus.EXPIRED, contract_value=88000.00, effective_date=date.today() - timedelta(days=760), expiry_date=date.today() - timedelta(days=30), auto_renew=False, ai_risk_score=42.0, ai_summary="Legacy hosting MSA; lapsed without renewal. Data-return clause requires confirmation of deletion."),
        ]
        for c in contracts:
            db.add(c)
        await db.flush()

        clauses = [
            ContractClause(id=_id(), tenant_id=TENANT, contract_id=contracts[0].id, clause_type="Limitation of Liability", original_text="Neither party's liability under this Agreement shall exceed the total amount paid by Customer in the 12 months preceding the event.", risk_level=ClauseRiskLevel.LOW, ai_analysis="Standard mutual limitation of liability. No high risk detected."),
            ContractClause(id=_id(), tenant_id=TENANT, contract_id=contracts[0].id, clause_type="Governing Law", original_text="This Agreement shall be governed by the laws of the State of New York.", risk_level=ClauseRiskLevel.NONE, ai_analysis="Standard governing-law clause; no risk."),
            ContractClause(id=_id(), tenant_id=TENANT, contract_id=contracts[1].id, clause_type="Indemnification", original_text="Contractor shall fully indemnify, defend, and hold harmless Owner from any and all claims, damages, and costs whatsoever without cap.", risk_level=ClauseRiskLevel.HIGH, ai_analysis="Uncapped unilateral indemnification is high risk. Contractor should negotiate a mutual cap linked to fee amounts."),
            ContractClause(id=_id(), tenant_id=TENANT, contract_id=contracts[1].id, clause_type="Confidentiality", original_text="Each party shall protect the other's Confidential Information using at least a reasonable standard of care.", risk_level=ClauseRiskLevel.MEDIUM, ai_analysis="Reasonable-care standard is vague; recommend a defined minimum security standard."),
            ContractClause(id=_id(), tenant_id=TENANT, contract_id=contracts[3].id, clause_type="Data Processing", original_text="Upon termination, Contractor shall delete or return all Customer Data within thirty (30) days.", risk_level=ClauseRiskLevel.MEDIUM, ai_analysis="Deletion window is unconfirmed post-expiry; request a certificate of destruction."),
        ]
        for cl in clauses:
            db.add(cl)

        template = ContractTemplate(
            id=_id(), tenant_id=TENANT, name="Mutual NDA Standard v2",
            contract_type="NDA", content="This Mutual Non-Disclosure Agreement is entered into by and between...",
            version="2.0.0", is_active=True
        )
        db.add(template)

        # 4. Compliance & Regulatory
        requirements = [
            RegulatoryRequirement(id=_id(), tenant_id=TENANT, regulation="GDPR", section="Article 30", title="Records of Processing Activities", description="Each controller shall maintain a record of processing activities under its responsibility.", jurisdiction="EU"),
            RegulatoryRequirement(id=_id(), tenant_id=TENANT, regulation="SOC2", section="CC6.1", title="Logical Access Controls", description="The entity restricts logical access to information assets, infrastructure, and software utilities.", jurisdiction="US")
        ]
        for r in requirements:
            db.add(r)
        await db.flush()

        obligations = [
            ComplianceObligation(id=_id(), tenant_id=TENANT, requirement_id=requirements[0].id, title="GDPR ROPA Annual Review", description="Update and verify registry of database tables holding customer PII.", owner="Elena Rostova", due_date=date.today() + timedelta(days=45), status=ObligationStatus.PENDING),
            ComplianceObligation(id=_id(), tenant_id=TENANT, requirement_id=requirements[1].id, title="SOC2 User Access Audit", description="Perform quarterly review of employee access privileges across AWS and SVB checking.", owner="Elena Rostova", due_date=date.today() - timedelta(days=5), status=ObligationStatus.OVERDUE, evidence_path="/compliance/soc2-q1-report.pdf"),
            ComplianceObligation(id=_id(), tenant_id=TENANT, requirement_id=requirements[1].id, title="SOC2 Vendor Risk Attestation", description="Collect signed SOC2/ISO attestations from all critical subprocessors.", owner="Elena Rostova", due_date=date.today() - timedelta(days=120), status=ObligationStatus.COMPLETED, evidence_path="/compliance/vendor-attestations-2025.pdf"),
            ComplianceObligation(id=_id(), tenant_id=TENANT, requirement_id=requirements[0].id, title="Legacy EU Data Transfer Review", description="Standard contractual clause review for a decommissioned EU processing pipeline.", owner="Elena Rostova", due_date=date.today() - timedelta(days=200), status=ObligationStatus.WAIVED),
        ]
        for o in obligations:
            db.add(o)

        assessments = [
            ComplianceAssessment(id=_id(), tenant_id=TENANT, framework="SOC2 Type II", assessment_date=date.today() - timedelta(days=90), assessor="Ernst & Young LLP", score=96.50, findings_count=1, report_path="/compliance/soc2-audit-report-2025.pdf"),
            ComplianceAssessment(id=_id(), tenant_id=TENANT, framework="ISO-27001", assessment_date=date.today() - timedelta(days=210), assessor="BSI Group", score=91.00, findings_count=3, report_path="/compliance/iso27001-audit-2025.pdf"),
            ComplianceAssessment(id=_id(), tenant_id=TENANT, framework="GDPR", assessment_date=date.today() - timedelta(days=30), assessor="Elena Rostova", score=88.25, findings_count=2, report_path="/compliance/gdpr-self-assessment-2026.pdf"),
        ]
        for a in assessments:
            db.add(a)

        # 5. Litigation Cases — spread across stages so the litigation charts
        # (exposure by stage, open-case counts) show real variety.
        cases = [
            Case(id=_id(), tenant_id=TENANT, case_name="KAEOS Inc. v. DeepCopy Corp", case_number="3:26-cv-04812", court="U.S. District Court, N.D. Cal.", stage=CaseStage.DISCOVERY, exposure_amount=500000.00, opposing_party="DeepCopy Corporation", opposing_counsel="Orrick Herrington LLP", lead_attorney_id=lawyers[1].id, description="Copyright infringement lawsuit against competitor for copying knowledge graph schemas.", outcome="Discovery phase active. Interrogatories served. Court-ordered mediation set for November."),
            Case(id=_id(), tenant_id=TENANT, case_name="Halberd Freight LLC v. KAEOS Inc.", case_number="1:26-cv-01187", court="U.S. District Court, S.D.N.Y.", stage=CaseStage.PLEADING, exposure_amount=175000.00, opposing_party="Halberd Freight LLC", opposing_counsel="Davis Polk LLP", lead_attorney_id=lawyers[0].id, description="Breach-of-contract claim over a terminated logistics integration SOW.", outcome=None),
            Case(id=_id(), tenant_id=TENANT, case_name="KAEOS Inc. v. Nakatomi Trading Co.", case_number="2:25-cv-09934", court="U.S. District Court, C.D. Cal.", stage=CaseStage.TRIAL, exposure_amount=1250000.00, opposing_party="Nakatomi Trading Co.", opposing_counsel="Quinn Emanuel LLP", lead_attorney_id=lawyers[1].id, description="Trade secret misappropriation claim against a former integration partner.", outcome="Trial commenced; jury selection complete, opening statements scheduled."),
            Case(id=_id(), tenant_id=TENANT, case_name="Meridian Analytics v. KAEOS Inc.", case_number="4:24-cv-05521", court="U.S. District Court, N.D. Cal.", stage=CaseStage.SETTLED, exposure_amount=60000.00, opposing_party="Meridian Analytics Inc.", opposing_counsel="Fenwick & West LLP", lead_attorney_id=lawyers[0].id, description="Wage-and-hour class claim from a former contractor cohort.", outcome="Settled for $60,000 with no admission of liability; release executed."),
        ]
        for case in cases:
            db.add(case)
        await db.flush()

        case_events = [
            CaseEvent(id=_id(), tenant_id=TENANT, case_id=cases[0].id, event_title="Deposition of CTO", event_date=date.today() + timedelta(days=20), description="Opposing counsel conducting deposition regarding patented ontology structures.", is_milestone="Yes"),
            CaseEvent(id=_id(), tenant_id=TENANT, case_id=cases[1].id, event_title="Initial Case Management Conference", event_date=date.today() + timedelta(days=35), description="Scheduling conference to set discovery and motion deadlines.", is_milestone="No"),
            CaseEvent(id=_id(), tenant_id=TENANT, case_id=cases[2].id, event_title="Jury Selection", event_date=date.today() - timedelta(days=2), description="Voir dire completed; jury of eight empaneled.", is_milestone="Yes"),
        ]
        for ce in case_events:
            db.add(ce)

        filings = [
            CourtFiling(id=_id(), tenant_id=TENANT, case_id=cases[0].id, document_name="Plaintiff's First Amended Complaint", filing_date=date.today() - timedelta(days=30), filed_by="Sarah Jenkins", document_path="/court/complaint-amended.pdf"),
            CourtFiling(id=_id(), tenant_id=TENANT, case_id=cases[1].id, document_name="Answer and Affirmative Defenses", filing_date=date.today() - timedelta(days=10), filed_by="Sarah Jenkins", document_path="/court/answer.pdf"),
            CourtFiling(id=_id(), tenant_id=TENANT, case_id=cases[3].id, document_name="Stipulation of Dismissal with Prejudice", filing_date=date.today() - timedelta(days=15), filed_by="Sarah Jenkins", document_path="/court/dismissal-stipulation.pdf"),
        ]
        for f in filings:
            db.add(f)

        # 6. Intellectual Property — patents and trademarks in varied statuses.
        patents = [
            Patent(id=_id(), tenant_id=TENANT, title="Method for Polling Decentralized LLM Agents", patent_number=None, application_number="18/901,234", filing_date=date.today() - timedelta(days=120), issue_date=None, expiry_date=None, status=IPStatus.PENDING, inventors="Dr. Arjun Sharma, Maya Patel", abstract="A method and system for query-level routing among multiple locally hosted and cloud-hosted LLM agents...", jurisdiction="USA"),
            Patent(id=_id(), tenant_id=TENANT, title="Governed Multi-Agent Gate Pipeline", patent_number="US11,982,340", application_number="17/455,908", filing_date=date.today() - timedelta(days=900), issue_date=date.today() - timedelta(days=210), expiry_date=date.today() + timedelta(days=6300), status=IPStatus.ACTIVE, inventors="Dr. Arjun Sharma", abstract="A sequential gate architecture for compliance, fairness, and human-in-the-loop review of autonomous agent decisions.", jurisdiction="USA"),
            Patent(id=_id(), tenant_id=TENANT, title="Heuristic Token-Cost Debate Matching", patent_number=None, application_number="18/334,771", filing_date=date.today() - timedelta(days=500), issue_date=None, expiry_date=None, status=IPStatus.ABANDONED, inventors="Maya Patel", abstract="A cost-matched peer debate protocol for resolving conflicting agent recommendations.", jurisdiction="USA"),
        ]
        for p in patents:
            db.add(p)

        trademarks = [
            Trademark(id=_id(), tenant_id=TENANT, mark_name="KAEOS", registration_number="7,891,012", filing_date=date.today() - timedelta(days=800), registration_date=date.today() - timedelta(days=400), renewal_date=date.today() + timedelta(days=3250), status=IPStatus.ACTIVE, class_code="Class 42", jurisdiction="USA"),
            Trademark(id=_id(), tenant_id=TENANT, mark_name="KAEOS COPILOT", registration_number=None, filing_date=date.today() - timedelta(days=60), registration_date=None, renewal_date=None, status=IPStatus.PENDING, class_code="Class 9", jurisdiction="USA"),
            Trademark(id=_id(), tenant_id=TENANT, mark_name="DIRECTIVES", registration_number="6,204,551", filing_date=date.today() - timedelta(days=2600), registration_date=date.today() - timedelta(days=2200), renewal_date=date.today() - timedelta(days=100), status=IPStatus.EXPIRED, class_code="Class 42", jurisdiction="USA"),
        ]
        for t in trademarks:
            db.add(t)

        secrets = [
            TradeSecret(id=_id(), tenant_id=TENANT, asset_name="Directives Fair-Play Debate Core Engine", description="Proprietary heuristics and token cost matching algorithm governing peer-to-peer agent debates.", custodian="Engineering Director", security_level="RESTRICTED"),
            TradeSecret(id=_id(), tenant_id=TENANT, asset_name="Reality Twin Synthesis Weights", description="Tuned parameter set for the org-graph reality twin's simulation and forecasting layer.", custodian="Head of Research", security_level="TOP_SECRET"),
        ]
        for s in secrets:
            db.add(s)

        # 7. Privacy DSARs — varied statuses so SLA-risk analytics show real signal.
        dsars = [
            DataSubjectRequest(id=_id(), tenant_id=TENANT, requestor_name="Ingrid Svensson", requestor_email="ingrid@svensson.se", request_type=DsarType.DELETE, status=DsarStatus.RECEIVED, request_date=date.today() - timedelta(days=1), deadline_date=date.today() + timedelta(days=29), assigned_officer="Elena Rostova", evidence_path="/privacy/passport-verification.pdf", ai_validation=False),
            DataSubjectRequest(id=_id(), tenant_id=TENANT, requestor_name="Javier Morales", requestor_email="javier@morales.es", request_type=DsarType.ACCESS, status=DsarStatus.COMPLETED, request_date=date.today() - timedelta(days=40), deadline_date=date.today() - timedelta(days=10), assigned_officer="Elena Rostova", evidence_path="/privacy/dl-verification.pdf", ai_validation=True),
            DataSubjectRequest(id=_id(), tenant_id=TENANT, requestor_name="Priya Nandakumar", requestor_email="priya.n@example.com", request_type=DsarType.PORTABILITY, status=DsarStatus.PROCESSING, request_date=date.today() - timedelta(days=24), deadline_date=date.today() + timedelta(days=3), assigned_officer="Elena Rostova", evidence_path="/privacy/id-verification-priya.pdf", ai_validation=True),
            DataSubjectRequest(id=_id(), tenant_id=TENANT, requestor_name="Tomas Weber", requestor_email="tomas.weber@example.de", request_type=DsarType.RESTRICT, status=DsarStatus.IDENTITY_VERIFIED, request_date=date.today() - timedelta(days=5), deadline_date=date.today() + timedelta(days=25), assigned_officer="Elena Rostova", evidence_path="/privacy/id-verification-tomas.pdf", ai_validation=False),
        ]
        for ds in dsars:
            db.add(ds)

        pias = [
            PrivacyImpactAssessment(id=_id(), tenant_id=TENANT, system_name="Employee Benefits Database Integration", pii_elements="First Name, Last Name, SSN, Health Insurance details", risk_rating="HIGH", remediation_required=True, status="SIGNED_OFF", signoff_date=date.today() - timedelta(days=12)),
            PrivacyImpactAssessment(id=_id(), tenant_id=TENANT, system_name="Marketing Analytics Warehouse", pii_elements="Email, Company, Job Title, Engagement Score", risk_rating="MEDIUM", remediation_required=False, status="SIGNED_OFF", signoff_date=date.today() - timedelta(days=60)),
            PrivacyImpactAssessment(id=_id(), tenant_id=TENANT, system_name="Support Ticket Transcript Store", pii_elements="Name, Email, Free-text Support Transcripts", risk_rating="LOW", remediation_required=False, status="DRAFT", signoff_date=None),
        ]
        for pia in pias:
            db.add(pia)

        ropa_records = [
            DataProcessingRecord(id=_id(), tenant_id=TENANT, data_controller="KAEOS HR Department", purpose_of_processing="Processing payroll and benefit enrollments.", categories_of_subjects="Employees, contractors, candidates", categories_of_recipients="ADP Inc, Blue Shield CA, AWS Cloud Hosting", retention_period="Employment duration plus 7 years regulatory requirement.", security_measures="AES-256 encryption at rest, TLS 1.3 in transit, role-based database permissions."),
            DataProcessingRecord(id=_id(), tenant_id=TENANT, data_controller="KAEOS Marketing Department", purpose_of_processing="Lead scoring and email campaign personalization.", categories_of_subjects="Prospects, newsletter subscribers", categories_of_recipients="HubSpot Inc, Segment Inc", retention_period="24 months from last engagement, then anonymized.", security_measures="TLS 1.3 in transit, tokenized email addresses in the analytics warehouse."),
        ]
        for r in ropa_records:
            db.add(r)

        await db.commit()
        print("[SUCCESS] Seeded Legal database:")
        print(f"   - {len(lawyers)} legal staff")
        print(f"   - {len(matters)} general matters")
        print(f"   - {len(contracts)} contracts, {len(clauses)} clause mappings")
        print(f"   - {len(obligations)} compliance obligations, {len(assessments)} compliance assessments")
        print(f"   - {len(cases)} litigation files, {len(case_events)} events, {len(filings)} filings")
        print(f"   - {len(patents)} patents, {len(trademarks)} trademarks, {len(secrets)} trade secrets")
        print(f"   - {len(dsars)} privacy requests, {len(pias)} PIAs, {len(ropa_records)} ROPA records")

if __name__ == "__main__":
    asyncio.run(seed())
