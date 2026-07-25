$files = Get-ChildItem "src\components\intelligence\*.tsx"
foreach ($f in $files) {
    $c = Get-Content $f.FullName -Raw
    $c = $c -replace '^"use client";', '"use client"'
    $c = $c -replace 'import React from "react";', ''
    Set-Content $f.FullName $c -Encoding UTF8
    Write-Host "Fixed $($f.Name)"
}