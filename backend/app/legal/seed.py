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
            LegalMatter(id=_id(), tenant_id=TENANT, title="Employee Dispute - Wrongful Termination", description="Disgruntled sales lead claiming unpaid commissions and wrongful dismissal.", matter_type="Employment", status=MatterStatus.NEW, priority=MatterPriority.MEDIUM, assigned_attorney_id=lawyers[0].id)
        ]
        for m in matters:
            db.add(m)
        await db.flush()

        # 3. Contracts
        contracts = [
            Contract(id=_id(), tenant_id=TENANT, title="Enterprise SaaS Agreement - Stark Ind", counterparty="Stark Industries Global", contract_type="MSA", status=ContractStatus.ACTIVE, contract_value=250000.00, effective_date=date.today() - timedelta(days=60), expiry_date=date.today() + timedelta(days=305), auto_renew=True, ai_risk_score=15.0, ai_summary="Standard outbound enterprise SaaS agreement. Governing law set to New York. Includes reciprocal IP protections."),
            Contract(id=_id(), tenant_id=TENANT, title="Strategic Partnership SOW - Wayne Corp", counterparty="Wayne Enterprises Inc", contract_type="SOW", status=ContractStatus.IN_REVIEW, contract_value=120000.00, effective_date=None, expiry_date=None, auto_renew=False)
        ]
        for c in contracts:
            db.add(c)
        await db.flush()

        clauses = [
            ContractClause(id=_id(), tenant_id=TENANT, contract_id=contracts[0].id, clause_type="Limitation of Liability", original_text="Neither party's liability under this Agreement shall exceed the total amount paid by Customer in the 12 months preceding the event.", risk_level=ClauseRiskLevel.LOW, ai_analysis="Standard mutual limitation of liability. No high risk detected."),
            ContractClause(id=_id(), tenant_id=TENANT, contract_id=contracts[1].id, clause_type="Indemnification", original_text="Contractor shall fully indemnify, defend, and hold harmless Owner from any and all claims, damages, and costs whatsoever without cap.", risk_level=ClauseRiskLevel.HIGH, ai_analysis="Uncapped unilateral indemnification is high risk. Contractor should negotiate a mutual cap linked to fee amounts.")
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
            ComplianceObligation(id=_id(), tenant_id=TENANT, requirement_id=requirements[1].id, title="SOC2 User Access Audit", description="Perform quarterly review of employee access privileges across AWS and SVB checking.", owner="Elena Rostova", due_date=date.today() - timedelta(days=5), status=ObligationStatus.OVERDUE, evidence_path="/compliance/soc2-q1-report.pdf")
        ]
        for o in obligations:
            db.add(o)

        assessment = ComplianceAssessment(
            id=_id(), tenant_id=TENANT, framework="SOC2 Type II",
            assessment_date=date.today() - timedelta(days=90), assessor="Ernst & Young LLP",
            score=96.50, findings_count=1, report_path="/compliance/soc2-audit-report-2025.pdf"
        )
        db.add(assessment)

        # 5. Litigation Cases
        cases = [
            Case(id=_id(), tenant_id=TENANT, case_name="KAEOS Inc. v. DeepCopy Corp", case_number="3:26-cv-04812", court="U.S. District Court, N.D. Cal.", stage=CaseStage.DISCOVERY, exposure_amount=500000.00, opposing_party="DeepCopy Corporation", opposing_counsel="Orrick Herrington LLP", lead_attorney_id=lawyers[1].id, description="Copyright infringement lawsuit against competitor for copying knowledge graph schemas.", outcome="Discovery phase active. Interrogatories served. Court-ordered mediation set for November."),
        ]
        for case in cases:
            db.add(case)
        await db.flush()

        case_event = CaseEvent(
            id=_id(), tenant_id=TENANT, case_id=cases[0].id,
            event_title="Deposition of CTO", event_date=date.today() + timedelta(days=20),
            description="Opposing counsel conducting deposition regarding patented ontology structures.",
            is_milestone="Yes"
        )
        db.add(case_event)

        filing = CourtFiling(
            id=_id(), tenant_id=TENANT, case_id=cases[0].id,
            document_name="Plaintiff's First Amended Complaint", filing_date=date.today() - timedelta(days=30),
            filed_by="Sarah Jenkins", document_path="/court/complaint-amended.pdf"
        )
        db.add(filing)

        # 6. Intellectual Property
        patent = Patent(
            id=_id(), tenant_id=TENANT, title="Method for Polling Decentralized LLM Agents",
            patent_number=None, application_number="18/901,234",
            filing_date=date.today() - timedelta(days=120), issue_date=None, expiry_date=None,
            status=IPStatus.PENDING, inventors="Dr. Arjun Sharma, Maya Patel",
            abstract="A method and system for query-level routing among multiple locally hosted and cloud-hosted LLM agents...",
            jurisdiction="USA"
        )
        db.add(patent)

        trademark = Trademark(
            id=_id(), tenant_id=TENANT, mark_name="KAEOS",
            registration_number="7,891,012", filing_date=date.today() - timedelta(days=800),
            registration_date=date.today() - timedelta(days=400), renewal_date=date.today() + timedelta(days=3250),
            status=IPStatus.ACTIVE, class_code="Class 42", jurisdiction="USA"
        )
        db.add(trademark)

        secret = TradeSecret(
            id=_id(), tenant_id=TENANT, asset_name="Directives Fair-Play Debate Core Engine",
            description="Proprietary heuristics and token cost matching algorithm governing peer-to-peer agent debates.",
            custodian="Engineering Director", security_level="RESTRICTED"
        )
        db.add(secret)

        # 7. Privacy DSARs
        dsars = [
            DataSubjectRequest(id=_id(), tenant_id=TENANT, requestor_name="Ingrid Svensson", requestor_email="ingrid@svensson.se", request_type=DsarType.DELETE, status=DsarStatus.RECEIVED, request_date=date.today() - timedelta(days=1), deadline_date=date.today() + timedelta(days=29), assigned_officer="Elena Rostova", evidence_path="/privacy/passport-verification.pdf", ai_validation=False),
            DataSubjectRequest(id=_id(), tenant_id=TENANT, requestor_name="Javier Morales", requestor_email="javier@morales.es", request_type=DsarType.ACCESS, status=DsarStatus.COMPLETED, request_date=date.today() - timedelta(days=40), deadline_date=date.today() - timedelta(days=10), assigned_officer="Elena Rostova", evidence_path="/privacy/dl-verification.pdf", ai_validation=True)
        ]
        for ds in dsars:
            db.add(ds)

        pia = PrivacyImpactAssessment(
            id=_id(), tenant_id=TENANT, system_name="Employee Benefits Database Integration",
            pii_elements="First Name, Last Name, SSN, Health Insurance details",
            risk_rating="HIGH", remediation_required=True, status="SIGNED_OFF",
            signoff_date=date.today() - timedelta(days=12)
        )
        db.add(pia)

        ropa = DataProcessingRecord(
            id=_id(), tenant_id=TENANT, data_controller="KAEOS HR Department",
            purpose_of_processing="Processing payroll and benefit enrollments.",
            categories_of_subjects="Employees, contractors, candidates",
            categories_of_recipients="ADP Inc, Blue Shield CA, AWS Cloud Hosting",
            retention_period="Employment duration plus 7 years regulatory requirement.",
            security_measures="AES-256 encryption at rest, TLS 1.3 in transit, role-based database permissions."
        )
        db.add(ropa)

        await db.commit()
        print("[SUCCESS] Seeded Legal database:")
        print(f"   - {len(lawyers)} legal staff")
        print(f"   - {len(matters)} general matters")
        print(f"   - {len(contracts)} contracts, {len(clauses)} clause mappings")
        print(f"   - {len(obligations)} compliance items")
        print(f"   - {len(cases)} litigation files")
        print(f"   - {len(dsars)} privacy requests")

if __name__ == "__main__":
    asyncio.run(seed())
