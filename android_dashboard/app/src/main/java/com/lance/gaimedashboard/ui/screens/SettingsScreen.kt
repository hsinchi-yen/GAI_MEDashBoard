package com.lance.gaimedashboard.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.lance.gaimedashboard.ui.theme.*
import com.lance.gaimedashboard.viewmodel.DashboardViewModel

@Composable
fun SettingsDialog(vm: DashboardViewModel, onDismiss: () -> Unit) {
    var keyInput     by remember { mutableStateOf(vm.fredApiKey) }
    var keyVisible   by remember { mutableStateOf(false) }
    val focusManager = LocalFocusManager.current

    Dialog(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(Surface)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Title
            Text(
                "⚙ 設定",
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold,
                color = OnSurface
            )

            HorizontalDivider(color = OutlineColor)

            // FRED API Key section
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    "FRED API Key",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = PrimaryTeal
                )
                Text(
                    "用於取得 VIX、殖利率、M1、PPI、原油等 FRED 資料。免費申請：fred.stlouisfed.org",
                    fontSize = 11.sp,
                    color = OnSurfaceVar,
                    lineHeight = 15.sp
                )

                OutlinedTextField(
                    value              = keyInput,
                    onValueChange      = { keyInput = it },
                    placeholder        = { Text("輸入您的 API Key", color = OnSurfaceVar, fontSize = 13.sp) },
                    singleLine         = true,
                    visualTransformation = if (keyVisible) VisualTransformation.None
                                          else PasswordVisualTransformation(),
                    trailingIcon       = {
                        IconButton(onClick = { keyVisible = !keyVisible }) {
                            Icon(
                                imageVector = if (keyVisible) Icons.Default.VisibilityOff
                                              else Icons.Default.Visibility,
                                contentDescription = null,
                                tint = OnSurfaceVar
                            )
                        }
                    },
                    keyboardOptions    = KeyboardOptions(
                        keyboardType = KeyboardType.Ascii,
                        imeAction    = ImeAction.Done
                    ),
                    keyboardActions    = KeyboardActions(onDone = { focusManager.clearFocus() }),
                    colors             = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor   = PrimaryTeal,
                        unfocusedBorderColor = OutlineColor,
                        cursorColor          = PrimaryTeal,
                        focusedTextColor     = OnSurface,
                        unfocusedTextColor   = OnSurface
                    ),
                    modifier = Modifier.fillMaxWidth()
                )
            }

            // Status indicator
            if (keyInput.isNotBlank()) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Box(
                        Modifier
                            .size(8.dp)
                            .clip(RoundedCornerShape(4.dp))
                            .background(Success)
                    )
                    Text("API Key 已設定（${keyInput.take(8)}...）", fontSize = 11.sp, color = Success)
                }
            } else {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Box(
                        Modifier
                            .size(8.dp)
                            .clip(RoundedCornerShape(4.dp))
                            .background(Amber)
                    )
                    Text("尚未設定 — PMI & CLI 仍可免費載入", fontSize = 11.sp, color = Amber)
                }
            }

            HorizontalDivider(color = OutlineColor)

            // Action buttons
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)
            ) {
                TextButton(onClick = onDismiss, colors = ButtonDefaults.textButtonColors(contentColor = OnSurfaceVar)) {
                    Text("取消")
                }
                Button(
                    onClick = {
                        vm.updateFredKey(keyInput)
                        vm.loadAll()
                        onDismiss()
                    },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = PrimaryTeal,
                        contentColor   = OnPrimary
                    )
                ) {
                    Text("儲存並重新載入", fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}
