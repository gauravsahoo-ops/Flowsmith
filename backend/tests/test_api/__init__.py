# Package marker so pytest imports these modules as
# ``tests.test_api.*`` like every other test directory. Without it,
# mixing root-level and test_api files in ONE pytest invocation can
# resolve fixtures from two different module identities (the recurring
# "fixture 'client'/'slow_node' not found" cross-suite failures).
