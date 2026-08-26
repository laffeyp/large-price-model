# Publishing

How a solo software engineer, with no quant or research background, gets a
pre-registered market-forecasting system in front of the readers who matter.
Written for this project specifically, and for the general shape of the problem
underneath it.

## The premise

The developer built a rare thing: an outsider-authored, open-source,
pre-registered market-forecasting system with reproducible infrastructure.
Nobody in the field routinely publishes work of that shape. Working quants sit
inside funds and don't publish. Retail bloggers publish freely and skip the
gate discipline. Academics publish gate-disciplined work but rarely with
runnable code. The intersection is small enough that the project's mere
existence carries signal, and the distribution strategy needs to protect that
signal rather than trade it for reach.

The asset is not returns. The asset is the combination of runnable code, an
honest pre-registration document, an artifact-hashed reproducibility chain,
and whichever result the eight gates return. The distribution problem is:
how does a solo SDE without credentials route the right readers to that
artifact?

## The repo is the primary artifact

The GitHub page is what strangers land on. It is the document. A README that
opens with the eight gates named in the first screen, followed by a link to
the pre-registration commit and a results table populated after the run, does
more work than any writeup elsewhere. A reader arriving from a Substack post,
an arXiv preprint, or a Twitter thread checks the repo before deciding whether
the writeup is honest. If the README delays the gates behind narrative, the
reader leaves.

Reproducibility instructions belong on the same page. The exact commands:
bucketize, train, evaluate, simulate. A one-line note on hardware — the $500
nominal budget and the AWS launcher under `scripts/aws/`. A pointer to
`signals/0.7.json` for the current signal vocabulary and to `configs/model/`
for the current architecture selection. The person deciding whether to spend
twenty minutes on the paper needs to know a real run is possible in the first
two minutes on the repo.

## Pre-registration is the outsider's leverage

Pre-registration is the single strongest honesty signal a stranger has. A file
committed to the public repo, timestamped by a git hash, containing the eight
gates and their thresholds, dated before any model has touched the held-out
window — that is a claim the reader can verify with `git log`. Most retail
quant writeups fail exactly this test. The reader assumes the gates were
chosen after the numbers came in, because the reader has been burned before by
exactly that.

The pre-registration document names each gate, its threshold, its statistical
definition, and the sample it will be computed on. It names what is not being
gated (drawdown magnitude, turnover, factor-neutralised alpha) and why. It
commits to publishing regardless of outcome. It reads in three minutes and a
working quant believes it. A pre-registration document that reads like an FDA
protocol is not the goal; a pre-registration document that reads like an
honest engineer thought hard about how they might fool themselves is the goal.

Post-hoc modifications to gates require a new commit that names the
modification, the reason, and the difference between the old and new number.
Silent tightening or loosening reads exactly like the failure mode
pre-registration exists to prevent.

## The two writeups

The technical writeup goes on SSRN or on arXiv q-fin. SSRN accepts any
submission. arXiv q-fin.TR (Trading and Market Microstructure) or q-fin.CP
(Computational Finance) needs a two-line endorsement from an existing q-fin
author, which practitioners give freely for honest work; a polite email with
the abstract and a repo link is the whole ask. Both venues put the paper into
the corpus that working quants search. Neither requires an affiliation. The
byline reads "Independent" and that is fine.

The paper follows the standard shape: abstract, data description with sources
and dates, methodology (bucketization, normalization, multi-channel
transformer, training, evaluation), results against the pre-registered gates,
discussion of the Corwin-Schultz calibration compromise and the other
design-level open items, limitations, conclusion. The paper cites the repo;
the repo does not cite the paper.

The story writeup goes on Substack and Hacker News. The angle is not "SDE
trades own account" and not "AI predicts market." The angle is: a software
engineer built a signal-driven development discipline around a
market-forecasting problem, pre-registered eight gates, and here is what the
gates said. Hacker News reads the meta-story — the 58 typed signal tags with
extras-strict payload validation, the artifact hashing with sha256 sidecars,
the three-look held-out budget enforced by a commit-msg hook — as an
engineering story worth its front page, and the quant result rides
underneath. Substack picks up traffic from HN and from the small ecosystem of
writers who cross-post: Corey Hoffstein's *Flirting with Models* newsletter,
Rob Carver's blog, *Robot James*, *quantitativo*, *quantymacro*.

## The infrastructure is its own artifact

The signal-driven development discipline is novel and separable from the
quant result. It is a way of building any system whose correctness depends on
out-of-sample generalization — recommendation systems, medical scoring,
credit models, ranking, any place where leakage between training and
evaluation is the primary failure mode. A talk titled "Signal-Driven
Development: What Financial Modeling Taught Me About Testing" lands at PyCon,
PyData, and Strange Loop regardless of whether the underlying model clears
its gates.

The reusable parts are concrete: the typed event vocabulary with
extras-strict payload validation at every call site (`signals/`), the frozen
artifact convention with sha256 sidecars (`src/price_space_llm/artifacts.py`),
the training-partition-only fit convention for tokenizers and normalizers,
the held-out budget enforced by both a runtime register and a commit-msg
hook. Each is a blog post. Together they are a talk. Extracted as a small
library, they are a package other people can depend on.

## Direct outreach beats broadcast

A targeted DM or email to four readers who would actually engage carries more
weight than a viral thread. Corey Hoffstein at Newfound Research replies to
well-written outsider work. Marcos López de Prado (Cornell, formerly
Guggenheim) publishes on exactly this class of problem. Rob Carver, author of
*Systematic Trading*, reads outsider work and reviews it in public. AQR's
research contact accepts unsolicited papers through a public form. One reply
from any of them reshapes a job conversation.

The message is short. Two sentences on what the project is. One link to the
pre-registration commit. One link to the results commit. No pitch, no ask, no
returns numbers with the gates left off. The message doesn't need to convince
the reader; it only needs to lower the click cost.

## Publish the negative result

Retail quant drowns in survivorship-biased writeups. A public failure with
full method disclosure — the pre-registration held, the run completed, gate 3
failed at threshold X, here is why the model probably fell short — is rare,
interesting, and lands harder than most passing results. It also proves the
pre-registration was real, which is the whole point of writing one.

A negative result is stronger job-application material than a marginal
positive one. The reader learns that the author can build the machinery,
execute the experiment, and report the answer honestly. That combination is
scarce enough to matter.

## What to ignore

Paid syndication services, "publish your alpha" platforms, LinkedIn
ghostwriters, engagement-farming reply threads — none of them route the
artifact to readers who matter. The audience that matters reads the paper and
the code. A recruiter who reaches out after the writeup and asks for the
returns before reading the pre-registration is not a serious recruiter.

Also ignore dashboards and interactive demos as the primary artifact. They
are fun to build and readers under-weight them. A markdown table of gate
results with a link to the code that produced it outperforms a Streamlit app
on every measure of technical credibility.

## Sequence

The order of operations matters more than the sum of the parts.

1. Commit the pre-registration document to the public repo, with the eight
   gates named and their thresholds set.
2. Run the training on AWS, with the run configuration itself committed and
   its outputs artifact-hashed.
3. Commit the results — the gate table populated, the evaluation notebook,
   the artifact hashes.
4. Post a preprint to SSRN, with an arXiv q-fin submission in parallel.
5. Publish the HN/Substack story writeup, pointing at both the preprint and
   the repo.
6. Send the four direct-outreach emails.
7. Submit a talk proposal to a nearby PyData or quant meetup.

Nothing in the sequence depends on the gate result. A pass and a fail follow
the same path; only the framing changes.

## The general pattern

The same pattern works outside quant. An outsider with a runnable artifact, a
public pre-registration, an honest result table, and direct outreach to four
people who would actually read it. This works for medical models, for climate
models, for machine-learning benchmarks — anywhere the primary failure mode
is "the author saw the data before choosing the metric." The credentialing
move is not credentials; it is verifiable honesty, and the verification runs
on the timestamps in the repo.

The audience is smaller than a viral thread reaches, and the audience is the
one that matters. A Twitter moment brings ten thousand people who don't read
the pre-registration. Four DMs to the right readers bring four who do. The
second number is the useful one.
