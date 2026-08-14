"""KAEOS Procurement department (first-class).

A thin orchestration package: it does NOT own its own tables. Procurement reuses
the Operations ``ops_*`` procurement models (PurchaseRequest, PurchaseOrder,
POLineItem, GoodsReceipt), the Finance three-way-match service, and the four
``app.compliance.checkers.procurement`` control checkers, binding them into a
controls-first source-to-pay flow (requisition -> PO -> goods receipt -> match).
"""
