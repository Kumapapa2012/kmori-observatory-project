// ========================================================
// USBFHD01M Slim Snap-Fit Case (Filleted/Tapered Cylinder Base)
// ========================================================

/* [表示モード選択] */
PART_SELECT = "all"; // ["all": 造形配置, "section": 嵌合断面確認, "mockup": 外観確認, "front": フロントカバー, "back": バックパネル]

/* [基本パラメータ (mm)] */
$fn = 64;

// カメラモジュール実寸法 (USBFHD01M)
pcb_w = 38.0;              
pcb_h = 38.0;              
pcb_t = 1.6;               
pcb_hole_pitch = 28.0;     // 28.0 × 28.0 mm 正方形ピッチ

lens_base_w = 20.0;        
lens_base_h = 10.5;        
lens_barrel_dia = 14.0;    
lens_total_h = 20.5;       
back_conn_h = 6.0;         

// ケース外形
wall = 2.0;                
case_w = 43.0;             
case_h = 43.0;             
corner_r = 3.0;            

// フロントカバー (タッピング対応・薄型)
front_depth = 11.5;        
lens_hole_dia = 16.0;      
pcb_boss_d = 5.0;          
pcb_boss_h = 11.0;         
pcb_boss_hole = 1.70;      // M2タッピング用下穴

// バックパネル (背面・円筒 & 三脚マウント)
back_depth = 10.0;         
cyl_id = 27.75;            // 円筒内径: 27.75mm
cyl_wall = 3.0;            // 円筒肉厚: 3.0mm
cyl_od = cyl_id + cyl_wall*2; // 円筒外径: 33.75mm
cyl_len = 27.75;           // 円筒突出長さ: 27.75mm
slit_w = 2.0;              
slit_len = 21.75;          // スリット深さ (手前6mm残し)
relief_hole_dia = 3.0;     
band_w = 9.0;              
band_depth = 0.6;          

// 根元補強テーパーパラメータ
taper_h = 4.5;             // テーパー高さ
taper_w = 2.5;             // テーパー張り出し幅 (根元外径は cyl_od + 5.0 = 38.75mm)

// 1/4インチ三脚マウントブロック
tripod_hole_dia = 8.0;     
tripod_hole_depth = 9.0;   
mount_block_w = 16.0;      
mount_block_h = 6.0;       

// スナップフィット パラメータ
snap_h = 2.5;              
snap_ridge_h = 0.55;       
snap_w = 10.0;             
pry_slot_w = 5.0;          

// ========================================================
// ダミーカメラモジュール
// ========================================================
module camera_module_mockup() {
    color([0.1, 0.6, 0.2, 0.9])
    difference() {
        cube([pcb_w, pcb_h, pcb_t], center=true);
        for (dx = [-pcb_hole_pitch/2, pcb_hole_pitch/2]) {
            for (dy = [-pcb_hole_pitch/2, pcb_hole_pitch/2]) {
                translate([dx, dy, -2]) cylinder(d=2.0, h=4);
            }
        }
    }
    // レンズ部
    color([0.2, 0.2, 0.2, 1.0]) {
        translate([0, 0, -pcb_t/2 - lens_base_h])
            cylinder(d=lens_base_w, h=lens_base_h);
        translate([0, 0, -pcb_t/2 - lens_total_h])
            cylinder(d=lens_barrel_dia, h=lens_total_h - lens_base_h);
        color([0.2, 0.5, 0.8, 0.8])
        translate([0, 0, -pcb_t/2 - lens_total_h - 0.1])
            cylinder(d=10, h=0.2);
    }
    // 背面コネクタ
    color([0.9, 0.9, 0.9, 1.0]) {
        translate([0, pcb_h/2 - 9 - 3, pcb_t/2 + back_conn_h/2])
            cube([10, 6, back_conn_h], center=true);
    }
}

module rounded_rect(w, h, depth, r) {
    linear_extrude(height=depth) {
        offset(r=r) {
            square([w - 2*r, h - 2*r], center=true);
        }
    }
}

// --------------------------------------------------------
// フロントカバー
// --------------------------------------------------------
module front_cover() {
    difference() {
        union() {
            rounded_rect(case_w, case_h, front_depth + wall, corner_r);
            
            // スナップ嵌合リップ
            translate([0, 0, front_depth + wall])
                difference() {
                    rounded_rect(case_w - wall*2 + 1.8, case_h - wall*2 + 1.8, snap_h, corner_r - 1);
                    translate([0, 0, -0.5])
                        rounded_rect(case_w - wall*2, case_h - wall*2, snap_h + 1, corner_r - 1.5);
                }
                
            // スナップ凸ビード
            for (dx = [-(case_w - wall*2 + 1.8)/2, (case_w - wall*2 + 1.8)/2]) {
                translate([dx, 0, front_depth + wall + snap_h - 0.8])
                    rotate([0, 90, 0])
                        cylinder(r=snap_ridge_h, h=snap_w, center=true);
            }
        }
        
        translate([0, 0, wall])
            rounded_rect(case_w - wall*2, case_h - wall*2, front_depth + snap_h + 2, corner_r - 1);
            
        translate([0, 0, -1])
            cylinder(d=lens_hole_dia, h=wall + 2);
    }
    
    // M2タッピング専用ボス (28×28mm 正方形ピッチ)
    for (dx = [-pcb_hole_pitch/2, pcb_hole_pitch/2]) {
        for (dy = [-pcb_hole_pitch/2, pcb_hole_pitch/2]) {
            translate([dx, dy, wall]) {
                difference() {
                    cylinder(d=pcb_boss_d, h=pcb_boss_h);
                    translate([0, 0, pcb_boss_h - 7.0])
                        cylinder(d=pcb_boss_hole, h=7.5);
                }
            }
        }
    }
}

// --------------------------------------------------------
// バックパネル (根元補強テーパー付き)
// --------------------------------------------------------
module back_panel() {
    difference() {
        union() {
            rounded_rect(case_w, case_h, back_depth + wall, corner_r);
            
            translate([-mount_block_w/2, -case_h/2 - mount_block_h, 0])
                cube([mount_block_w, mount_block_h + 2, back_depth + wall]);

            // 円筒部ストレート本体
            translate([0, 0, -cyl_len])
                cylinder(d=cyl_od, h=cyl_len);
                
            // ★根元の補強テーパー (コーン状リブ)
            translate([0, 0, -taper_h])
                cylinder(d1=cyl_od, d2=cyl_od + taper_w*2, h=taper_h);

            // 先端の抜け止めリブ
            translate([0, 0, -cyl_len])
                cylinder(d=cyl_od + 1.2, h=2.0);
        }
        
        translate([0, 0, wall])
            rounded_rect(case_w - wall*2, case_h - wall*2, back_depth + 1, corner_r - 1);
            
        translate([0, 0, back_depth + wall - snap_h - 0.2])
            difference() {
                rounded_rect(case_w - wall*2 + 2.4, case_h - wall*2 + 2.4, snap_h + 1, corner_r - 0.8);
                translate([0, 0, -0.5])
                    rounded_rect(case_w - wall*2 - 0.5, case_h - wall*2 - 0.5, snap_h + 2, corner_r - 1.5);
            }

        for (dx = [-(case_w - wall*2 + 2.1)/2, (case_w - wall*2 + 2.1)/2]) {
            translate([dx, 0, back_depth + wall - 0.8])
                rotate([0, 90, 0])
                    cylinder(r=snap_ridge_h + 0.15, h=snap_w + 2, center=true);
        }

        for (dx = [-case_w/2, case_w/2]) {
            translate([dx, 0, back_depth + wall])
                cube([3.0, pry_slot_w, 2.0], center=true);
        }

        // 円筒内径貫通
        translate([0, 0, -cyl_len - 1])
            cylinder(d=cyl_id, h=cyl_len + wall + 2);

        // 内側配線通過用の面取りテーパー
        translate([0, 0, -1])
            cylinder(d1=cyl_id + 3.0, d2=cyl_id, h=wall + 1.1);
            
        // バンド収容溝
        translate([0, 0, -cyl_len + 3.0])
            difference() {
                cylinder(d=cyl_od + 2, h=band_w);
                cylinder(d=cyl_od - band_depth*2, h=band_w);
            }

        // 90度スリット & 応力緩和穴
        for (a = [0, 90, 180, 270]) {
            rotate([0, 0, a]) {
                translate([-slit_w/2, 0, -cyl_len - 1])
                    cube([slit_w, cyl_od + 4, slit_len + 1]);
                    
                translate([0, (cyl_id + cyl_wall)/2, -cyl_len + slit_len])
                    rotate([0, 90, 0])
                        cylinder(d=relief_hole_dia, h=cyl_od + 4, center=true);
            }
        }
        
        // 1/4" 下穴
        translate([0, -case_h/2 - mount_block_h - 1, (back_depth + wall)/2])
            rotate([-90, 0, 0])
                cylinder(d=tripod_hole_dia, h=tripod_hole_depth + 1);
    }
}

// ========================================================
// レンダリング分岐
// ========================================================
if (PART_SELECT == "section") {
    difference() {
        union() {
            color([0.9, 0.7, 0.2]) front_cover();
            translate([0, 0, front_depth + wall + back_depth + wall])
                rotate([180, 0, 0])
                    color([0.8, 0.6, 0.2]) back_panel();
            translate([0, 0, wall + pcb_boss_h + pcb_t/2])
                camera_module_mockup();
        }
        translate([0, -case_h - 10, -cyl_len - 10])
            cube([case_w + 20, (case_h + 10) * 2, front_depth + cyl_len + back_depth + 40]);
    }

} else if (PART_SELECT == "mockup") {
    color([0.9, 0.7, 0.2, 0.5]) front_cover();
    translate([0, 0, front_depth + wall + back_depth + wall])
        rotate([180, 0, 0])
            color([0.8, 0.6, 0.2, 0.5]) back_panel();
    translate([0, 0, wall + pcb_boss_h + pcb_t/2])
        camera_module_mockup();

} else if (PART_SELECT == "all") {
    translate([-(case_w/2 + 5), 0, 0]) 
        front_cover();
    translate([(case_w/2 + 5), 0, 0]) 
        rotate([180, 0, 0])
        translate([0, 0, -(back_depth + wall)])
            back_panel();

} else if (PART_SELECT == "front") {
    front_cover();

} else if (PART_SELECT == "back") {
    rotate([180, 0, 0])
    translate([0, 0, -(back_depth + wall)])
        back_panel();
}