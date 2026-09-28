# Frozen evaluation Sheet

`Performance.csv` is the immutable local representation of the eval-only Google
Sheet. Its single `Performance` tab has the exact `A:D` column shape in
`docs/data-contract.yaml`: `date`, `revenue`, `segment`, and `orders`.

It is synthetic and is never a real-Investigation data source. Dataset scenarios
refer to it as `frozen-eval-sheet`, not to the production `fixture-sheet` ID.
Known answers are captured with each scenario so fixture changes cannot silently
change evaluation ground truth.
