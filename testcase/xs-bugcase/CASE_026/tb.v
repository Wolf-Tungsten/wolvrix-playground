module xs_bugcase_tb (
  input [7:0] hits,
  input [21:0] entry_target,
  input [48:0] expected_target,
  input [4:0] entry_position,
  input [4:0] prediction_position,
  input [1:0] entry_branch_type,
  input [1:0] prediction_branch_type,
  input [1:0] entry_ras,
  input [1:0] prediction_ras,
  input t1_fire,
  input [3:0] bank_mask,
  output out_hit,
  output [7:0] out_selected,
  output out_need_correct,
  output out_write_bank0
);
  wire abtb_entry_t [7:0] entries;
  for (genvar i = 0; i < 8; i = i + 1) begin : gen_entries
    assign entries[i] = '{
      hit: hits[i],
      attribute_0: '{branchType: entry_branch_type, rasAction: entry_ras},
      position: entry_position,
      targetLowerBits: entry_target
    };
  end

  wire abtb_train_t train = '{
    finalPrediction: '{
      cfiPosition: prediction_position,
      target: '{addr: expected_target},
      attribute_0: '{branchType: prediction_branch_type, rasAction: prediction_ras}
    },
    abtbMeta: '{entries: entries}
  };

  AheadBtbTargetCorrect dut (
    .t1_train(train),
    .t1_fire(t1_fire),
    .bankMask(bank_mask),
    .out_hit(out_hit),
    .out_selected(out_selected),
    .out_need_correct(out_need_correct),
    .out_write_bank0(out_write_bank0)
  );
endmodule
