"""Audit event types of the materials area that `LibraryAuditType` does not list.

The shared enum holds the names identity and the library agreed on; these three
decisions also write an audit event (GEN-6), so they get names of the same family.
"""

REQUEST_CHANGES = "library.request_changes"
REPORT_DISMISS = "library.report_dismiss"
SUGGESTION = "library.suggestion"
