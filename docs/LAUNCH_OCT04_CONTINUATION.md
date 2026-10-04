# AccessDoc October4 continuation — HOLD

Published measured raw receipts in docs/evidence/launch-oct04-continuation/. PR95 body contains audit, premortem, tool rationale, current versus historical benchmarks, source identities and exact engineering/owner actions.

Candidate4a12b29 local:1221passed/23skipped/436subtests,69.91s;focused63passed/3subtests,4.08s. Existing browser skips disclosed. Windows hosted green. macOS hosted FAILED the original50ms deadline success-bound assertion; no all-OS or GO claim. Collector pacing change is fixture-only; production deadlines and retries unchanged. Remaining scheduler/timer-release overshoot is unresolved engineering work,not an owner action. Failure annotations retained here. Latest evidence-only ecd88a1 checks pending at freeze.

Main7ab1817 unchanged;PR95draft,auto-mergeoff. Historical live main health/ready200 but authnotrequired,gatewayunconfigured. No deployment,payment,live model calls or practitioner assent.

Local pilot:privately supply fresh ACCESSDOC_API_KEY;install requirements.txt;run python3 scripts/start_zero_spend_pilot.py. Refuses missingkey,bindsloopback,stripsMeliouscredential,authon,HTTPremediationoff,30minretention. Actual synthetic missing/wrongkey401,correctbundle200,remediation503,health200verified.

Owner actions:rotate exposedcredentials;approve protectedverification and privately provision matchingpilot/bypasssecrets;approve eligiblezerochargehosting and terms,fleet/WAF/logretention/rollback;confirmfreemodelentitlement or explicitpaidbudget beforelivefourmodelstress;obtain genuinepractitioner/AT/security/legal/operatoracceptance throughissues96–98. Engineering must first resolve50msdeadlinefailure andproveallOS,targettorture andleak/resourcegates. No mergeuntilALLgatesclose.
