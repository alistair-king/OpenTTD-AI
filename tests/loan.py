"""Isolated live-game loan repayment test; copies the AI into a temporary working folder."""
from pathlib import Path
import re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
exe = Path.home() / 'Library/Application Support/Steam/steamapps/common/OpenTTD/OpenTTD.app/Contents/MacOS/openttd'
config = (Path.home() / 'Documents/OpenTTD/openttd.cfg').read_text().replace('OpenTTDAI =', 'LoanCheck =')
for key, value in {'autosave_interval':'0', 'autosave_on_exit':'false', 'map_x':'7', 'map_y':'7', 'terrain_type':'0', 'max_no_competitors':'1'}.items():
    config = re.sub(r'^' + key + r' = .*$', key + ' = ' + value, config, flags=re.M)
config = re.sub(r'\[ai_players\][\s\S]*?(?=\n\[|\Z)', '[ai_players]\nLoanCheck = \n', config)
driver = r'''
::repayment_test_balance <- 0;
::real_company <- AICompany;
function OpenTTDAI::Start()
{
    this.Sleep(1);
    local original_bank=AICompany.GetBankBalance;
    // Control the eligibility reading; repayments still execute in the game.
    ::AICompany = {
        COMPANY_SELF = real_company.COMPANY_SELF,
        GetBankBalance = function(company) { return repayment_test_balance; },
        GetLoanAmount = function() { return real_company.GetLoanAmount(); },
        GetLoanInterval = function() { return real_company.GetLoanInterval(); },
        SetLoanAmount = function(amount) { return real_company.SetLoanAmount(amount); }
    };
    local loan=AICompany.GetLoanAmount();
    repayment_test_balance=2*loan-1;
    if(RepaySurplusLoan() || AICompany.GetLoanAmount()!=loan) {
        AILog.Error("LOAN FAIL: premature repayment"); return;
    }
    // Exercise the annual guard and its save/load persistence before the
    // remaining arithmetic checks (which call the repayment helper directly).
    repayment_test_balance=2*loan;
    if(!this.ReviewLoan() || this.ReviewLoan()) { AILog.Error("LOAN FAIL: annual guard"); return; }
    local saved=this.Save();
    this.last_loan_repayment_year=-1;
    this.Load(1,saved);
    if(this.ReviewLoan()) { AILog.Error("LOAN FAIL: reload repaid twice"); return; }
    this.last_loan_repayment_year=AIDate.GetYear(AIDate.GetCurrentDate())-1;
    if(!this.ReviewLoan()) { AILog.Error("LOAN FAIL: next year blocked"); return; }
    loan=AICompany.GetLoanAmount();
    for(local attempts=0;attempts<20 && loan>0;attempts++) {
        repayment_test_balance=2*loan;
        local cash=original_bank(AICompany.COMPANY_SELF);
        local expected=(loan/2/AICompany.GetLoanInterval())*AICompany.GetLoanInterval();
        if(!RepaySurplusLoan() || AICompany.GetLoanAmount()!=expected ||
            original_bank(AICompany.COMPANY_SELF)!=cash-(loan-expected)) {
            AILog.Error("LOAN FAIL: half repayment or bank accounting"); return;
        }
        loan=AICompany.GetLoanAmount();
    }
    if(loan!=0 || RepaySurplusLoan()) { AILog.Error("LOAN FAIL: final repayment"); return; }
    ::AICompany = real_company;
    AILog.Info("LOAN PASS: threshold boundary, real repayments, bank accounting and full clearance.");
    while(true) this.Sleep(1000);
}
'''
with tempfile.TemporaryDirectory(prefix='openttdai-loan-') as td:
    folder = Path(td)
    ai = folder / 'ai' / 'LoanCheck'
    ai.mkdir(parents=True)
    for source in root.glob('*.nut'):
        shutil.copy2(source, ai / source.name)
    info = ai / 'info.nut'
    info.write_text(info.read_text().replace('return "OpenTTDAI";', 'return "LoanCheck";', 1))
    main = ai / 'main.nut'
    main.write_text(main.read_text().replace('function OpenTTDAI::Start()', 'function OpenTTDAI::UnusedStart()') + driver)
    cfg = folder / 'openttd.cfg'
    cfg.write_text(config)
    for seed in [42, 7]:
        result = subprocess.run([str(exe), '-c', str(cfg), '-x', '-v', 'null:ticks=180000', '-s', 'null', '-m', 'null', '-g', '-G', str(seed), '-d', 'script=4'], cwd=folder, text=True, capture_output=True, timeout=60)
        (root / 'tests' / f'loan-{seed}.log').write_text(result.stderr)
        print('SEED', seed, '\n', result.stderr[-4500:], flush=True)
        assert result.returncode == 0 and 'LOAN PASS:' in result.stderr
        assert 'LOAN FAIL:' not in result.stderr
