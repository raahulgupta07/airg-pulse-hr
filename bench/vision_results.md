# Vision Bench Results

Doc: bench_input.png (Myanmar driver form)

| Model | Field acc | OCR chars | Latency | Cost | Wins |
|---|---|---|---|---|---|
| `google/gemini-3-flash-preview` | 17/17 (100%) | 540 | 7409ms | $0.00160 | applied_position, name, father, nrc, dob… |
| `google/gemini-3.1-flash-lite-preview` | 17/17 (100%) | 538 | 7305ms | $0.00033 | applied_position, name, father, nrc, dob… |
| `google/gemini-3.1-pro-preview` | 17/17 (100%) | 558 | 72764ms | $0.09903 | applied_position, name, father, nrc, dob… |
| `openai/gpt-5.4-mini` | 14/17 (82%) | 542 | 4095ms | $0.00032 | applied_position, name, father, nrc, dob… |
| `openai/gpt-5.4` | 14/17 (82%) | 694 | 8160ms | $0.00500 | applied_position, name, father, nrc, dob… |
| `anthropic/claude-haiku-4.5` | 15/17 (88%) | 652 | 8185ms | $0.00275 | applied_position, name, father, nrc, dob… |
| `anthropic/claude-sonnet-4.6` | 17/17 (100%) | 731 | 15195ms | $0.01105 | applied_position, name, father, nrc, dob… |
| `anthropic/claude-opus-4.7` | 17/17 (100%) | 645 | 10012ms | $0.05994 | applied_position, name, father, nrc, dob… |
| `anthropic/claude-3.7-sonnet` | 16/17 (94%) | 677 | 15030ms | $0.00977 | applied_position, name, father, nrc, dob… |
| `mistralai/pixtral-large-2411` | 15/17 (88%) | 682 | 9892ms | $0.00682 | applied_position, name, father, dob, religion… |
