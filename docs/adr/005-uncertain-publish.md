# ADR-005: Ambiguous final publish results are not retried automatically

**Status:** Accepted

A timeout or connection loss after final request start transitions to `PUBLISH_UNCERTAIN`. Manual verification is required because blind retry can duplicate the post.
